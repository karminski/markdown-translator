"""
Concurrent translation processing system.

This module manages the translation of file chunks using OpenRouter API
with concurrent processing and error handling.
"""

import asyncio
import time
import logging
import random
from typing import List, Optional, Dict, Any, Tuple
from openai import OpenAI, APIError, RateLimitError, APITimeoutError
from .interfaces import ITranslator, IValidator
from .models import FileChunk, TranslationResult, TranslationStatus, ValidationResult
from .performance import PerformanceMonitor
from .security import SecurityManager


class RetryStrategy:
    """Configuration for retry behavior."""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0, 
                 exponential_base: float = 2.0, jitter: bool = True):
        """
        Initialize retry strategy.
        
        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Base delay in seconds for first retry
            max_delay: Maximum delay in seconds
            exponential_base: Base for exponential backoff
            jitter: Whether to add random jitter to delays
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay for given attempt number.
        
        Args:
            attempt: Attempt number (0-based)
            
        Returns:
            Delay in seconds
        """
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            # Add ±25% jitter
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)
        
        return max(0, delay)


class TranslationPool(ITranslator):
    """
    Concurrent translation processing pool that manages translation of file chunks.
    
    This class implements the ITranslator interface and provides:
    - Asynchronous translation processing with configurable concurrency
    - Semaphore-based concurrency control
    - OpenRouter API integration
    - Exponential backoff retry mechanism
    - API rate limiting handling
    - Integrity validation integration
    - Error classification and recovery
    """
    
    def __init__(self, concurrency: int = 5, api_client: Optional[OpenAI] = None, 
                 validator: Optional[IValidator] = None, retry_strategy: Optional[RetryStrategy] = None,
                 performance_monitor: Optional[PerformanceMonitor] = None,
                 security_manager: Optional[SecurityManager] = None):
        """
        Initialize the translation pool.
        
        Args:
            concurrency: Maximum number of concurrent translation tasks
            api_client: Configured OpenAI client for API calls
            validator: Content integrity validator
            retry_strategy: Retry configuration
            performance_monitor: Performance monitoring instance
            security_manager: Security manager instance
        """
        self.concurrency = concurrency
        self.api_client = api_client
        self.validator = validator
        self.retry_strategy = retry_strategy or RetryStrategy()
        self.performance_monitor = performance_monitor
        self.security_manager = security_manager
        self.semaphore = asyncio.Semaphore(concurrency)
        self.logger = logging.getLogger(__name__)
        
        # Rate limiting state
        self._rate_limit_delay = 0.0
        self._last_rate_limit_time = 0.0
        
        if not self.api_client:
            raise ValueError("API client is required for translation")
    
    async def translate_chunks(self, chunks: List[FileChunk]) -> List[TranslationResult]:
        """
        Translate a list of file chunks concurrently.
        
        Args:
            chunks: List of FileChunk objects to translate
            
        Returns:
            List of TranslationResult objects with translation results
        """
        if not chunks:
            return []
        
        self.logger.info(f"Starting translation of {len(chunks)} chunks with concurrency {self.concurrency}")
        
        # Create translation tasks
        tasks = []
        for chunk in chunks:
            task = asyncio.create_task(self._translate_single_chunk_with_semaphore(chunk))
            tasks.append(task)
        
        # Wait for all translations to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results and handle exceptions
        translation_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # Create a failed result for exceptions
                chunk = chunks[i]
                failed_result = TranslationResult(
                    chunk_id=chunk.id,
                    original_content=chunk.content,
                    translated_content="",
                    success=False,
                    sequence_number=chunk.sequence_number,
                    error_message=str(result),
                    status=TranslationStatus.FAILED
                )
                translation_results.append(failed_result)
                self.logger.error(f"Translation failed for chunk {chunk.id}: {result}")
            else:
                translation_results.append(result)
        
        successful = sum(1 for r in translation_results if r.success)
        self.logger.info(f"Translation completed: {successful}/{len(chunks)} successful")
        
        return translation_results
    
    async def translate_single_chunk(self, chunk: FileChunk) -> TranslationResult:
        """
        Translate a single file chunk.
        
        Args:
            chunk: FileChunk object to translate
            
        Returns:
            TranslationResult object with the translation result
        """
        return await self._translate_single_chunk_with_semaphore(chunk)
    
    async def _translate_single_chunk_with_semaphore(self, chunk: FileChunk) -> TranslationResult:
        """
        Translate a single chunk with semaphore control.
        
        Args:
            chunk: FileChunk to translate
            
        Returns:
            TranslationResult with translation outcome
        """
        async with self.semaphore:
            return await self._translate_chunk_internal(chunk)
    
    async def _translate_chunk_internal(self, chunk: FileChunk) -> TranslationResult:
        """
        Internal method to translate a single chunk with retry logic and validation.
        
        Args:
            chunk: FileChunk to translate
            
        Returns:
            TranslationResult with translation outcome
        """
        start_time = time.time()
        last_error = None
        
        # Record concurrent operations for performance monitoring
        if self.performance_monitor:
            self.performance_monitor.record_concurrent_operations(self.concurrency)
        
        # Security validation of chunk content
        if self.security_manager:
            content_validation = self.security_manager.validate_content(chunk.content)
            if not content_validation.is_valid and content_validation.risk_level == 'high':
                processing_time = time.time() - start_time
                return TranslationResult(
                    chunk_id=chunk.id,
                    original_content=chunk.content,
                    translated_content="",
                    success=False,
                    sequence_number=chunk.sequence_number,
                    error_message=f"Security validation failed: {', '.join(content_validation.issues)}",
                    processing_time=processing_time,
                    status=TranslationStatus.FAILED
                )
        
        for attempt in range(self.retry_strategy.max_retries + 1):
            try:
                self.logger.debug(f"Translation attempt {attempt + 1} for chunk {chunk.id}")
                
                # Apply rate limiting delay if needed
                await self._apply_rate_limit_delay()
                
                # Prepare content with integrity markers if validator is available
                content_to_translate = chunk.content
                if self.validator:
                    content_to_translate = self.validator.add_markers(chunk.content)
                
                # Create translation prompt
                prompt = self._create_translation_prompt(content_to_translate)
                
                # Make API call with retry handling and performance monitoring
                api_start_time = time.time()
                response = await asyncio.to_thread(
                    self._make_api_call_with_retry,
                    prompt
                )
                api_duration = time.time() - api_start_time
                
                # Record API performance
                if self.performance_monitor:
                    self.performance_monitor.record_api_call(api_duration, True)
                
                # Security validation of API response
                if self.security_manager:
                    response_validation = self.security_manager.validate_api_response(response)
                    if not response_validation.is_valid and response_validation.risk_level == 'high':
                        error_msg = f"API response security validation failed: {', '.join(response_validation.issues)}"
                        self.logger.warning(f"Chunk {chunk.id} API response validation failed: {error_msg}")
                        if attempt < self.retry_strategy.max_retries:
                            await self._apply_retry_delay(attempt)
                            continue
                        else:
                            processing_time = time.time() - start_time
                            return TranslationResult(
                                chunk_id=chunk.id,
                                original_content=chunk.content,
                                translated_content="",
                                success=False,
                                sequence_number=chunk.sequence_number,
                                error_message=error_msg,
                                retry_count=attempt,
                                processing_time=processing_time,
                                status=TranslationStatus.FAILED
                            )
                
                # Extract translated content
                translated_content = self._extract_translation_from_response(response)
                
                # Validate translation if validator is available
                if self.validator:
                    validation_result = self.validator.validate_translation(
                        content_to_translate, translated_content
                    )
                    
                    if not validation_result.is_valid:
                        # Validation failed, treat as retriable error
                        error_msg = f"Validation failed: {', '.join(validation_result.issues)}"
                        self.logger.warning(f"Chunk {chunk.id} validation failed on attempt {attempt + 1}: {error_msg}")
                        
                        if attempt < self.retry_strategy.max_retries:
                            await self._apply_retry_delay(attempt)
                            continue
                        else:
                            # Final attempt failed validation
                            processing_time = time.time() - start_time
                            return TranslationResult(
                                chunk_id=chunk.id,
                                original_content=chunk.content,
                                translated_content="",
                                success=False,
                                sequence_number=chunk.sequence_number,
                                error_message=error_msg,
                                retry_count=attempt,
                                processing_time=processing_time,
                                status=TranslationStatus.FAILED
                            )
                    
                    # Remove markers from validated content
                    translated_content = self.validator.remove_markers(translated_content)
                
                # Success!
                processing_time = time.time() - start_time
                
                # Record chunk processing performance
                if self.performance_monitor:
                    self.performance_monitor.record_chunk_processing(processing_time)
                
                result = TranslationResult(
                    chunk_id=chunk.id,
                    original_content=chunk.content,
                    translated_content=translated_content,
                    success=True,
                    sequence_number=chunk.sequence_number,
                    retry_count=attempt,
                    processing_time=processing_time,
                    status=TranslationStatus.COMPLETED
                )
                
                self.logger.debug(f"Translation completed for chunk {chunk.id} in {processing_time:.2f}s after {attempt + 1} attempts")
                return result
                
            except Exception as e:
                last_error = e
                error_type = self._classify_error(e)
                
                # Record failed API call for performance monitoring
                if self.performance_monitor and 'api_start_time' in locals():
                    api_duration = time.time() - api_start_time
                    self.performance_monitor.record_api_call(api_duration, False)
                
                self.logger.warning(f"Translation attempt {attempt + 1} failed for chunk {chunk.id}: {e}")
                
                # Check if error is retriable
                if not self._is_retriable_error(error_type) or attempt >= self.retry_strategy.max_retries:
                    break
                
                # Handle specific error types
                if error_type == "rate_limit":
                    await self._handle_rate_limit_error(e)
                
                # Apply retry delay
                await self._apply_retry_delay(attempt)
        
        # All retries exhausted
        processing_time = time.time() - start_time
        error_message = str(last_error) if last_error else "Unknown error"
        
        result = TranslationResult(
            chunk_id=chunk.id,
            original_content=chunk.content,
            translated_content="",
            success=False,
            sequence_number=chunk.sequence_number,
            error_message=error_message,
            retry_count=self.retry_strategy.max_retries,
            processing_time=processing_time,
            status=TranslationStatus.FAILED
        )
        
        self.logger.error(f"Translation failed for chunk {chunk.id} after {self.retry_strategy.max_retries + 1} attempts: {error_message}")
        return result
    
    def _create_translation_prompt(self, content: str) -> str:
        """
        Create a translation prompt for the given content.
        
        Args:
            content: Content to translate
            
        Returns:
            Formatted prompt for translation
        """
        prompt = f"""请将以下Markdown内容翻译成中文，保持所有Markdown格式不变：

{content}

要求：
1. 保持所有Markdown语法结构完整（标题、列表、代码块、链接等）
2. 只翻译文本内容，不要翻译代码、命令、文件名等技术内容
3. 保持原有的换行和缩进格式
4. 确保翻译准确、自然、符合中文表达习惯
5. 不要添加任何额外的解释或注释"""
        
        return prompt
    
    def _make_api_call_with_retry(self, prompt: str) -> Dict[str, Any]:
        """
        Make synchronous API call to OpenRouter with error handling.
        
        Args:
            prompt: Translation prompt
            
        Returns:
            API response dictionary
            
        Raises:
            Exception: If API call fails
        """
        try:
            response = self.api_client.chat.completions.create(
                model="qwen/qwen-2.5-72b-instruct",  # Default model
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,  # Lower temperature for more consistent translations
                max_tokens=4000,  # Reasonable limit for chunk translations
                timeout=30.0,  # 30 second timeout
            )
            
            return response.model_dump()
            
        except Exception as e:
            self.logger.error(f"API call failed: {e}")
            raise
    
    def _extract_translation_from_response(self, response: Dict[str, Any]) -> str:
        """
        Extract translated content from API response.
        
        Args:
            response: API response dictionary
            
        Returns:
            Extracted translated content
            
        Raises:
            ValueError: If response format is invalid
        """
        try:
            choices = response.get('choices', [])
            if not choices:
                raise ValueError("No choices in API response")
            
            message = choices[0].get('message', {})
            content = message.get('content', '')
            
            if not content:
                raise ValueError("No content in API response")
            
            return content.strip()
            
        except Exception as e:
            self.logger.error(f"Failed to extract translation from response: {e}")
            raise ValueError(f"Invalid API response format: {e}")
    
    def get_concurrency(self) -> int:
        """Get the current concurrency level."""
        return self.concurrency
    
    def set_concurrency(self, concurrency: int) -> None:
        """
        Set the concurrency level for translation.
        
        Args:
            concurrency: New concurrency level (must be > 0)
        """
        if concurrency <= 0:
            raise ValueError("Concurrency must be greater than 0")
        
        self.concurrency = concurrency
        self.semaphore = asyncio.Semaphore(concurrency)
        self.logger.info(f"Concurrency updated to {concurrency}")
    
    def get_api_client(self) -> OpenAI:
        """Get the current API client."""
        return self.api_client
    
    def set_api_client(self, api_client: OpenAI) -> None:
        """
        Set a new API client.
        
        Args:
            api_client: New OpenAI client instance
        """
        if not api_client:
            raise ValueError("API client cannot be None")
        
        self.api_client = api_client
        self.logger.info("API client updated")
    
    def set_validator(self, validator: IValidator) -> None:
        """
        Set the integrity validator.
        
        Args:
            validator: Integrity validator instance
        """
        self.validator = validator
        self.logger.info("Integrity validator updated")
    
    def _classify_error(self, error: Exception) -> str:
        """
        Classify error type for appropriate handling.
        
        Args:
            error: Exception to classify
            
        Returns:
            Error type string
        """
        if isinstance(error, RateLimitError):
            return "rate_limit"
        elif isinstance(error, APITimeoutError):
            return "timeout"
        elif isinstance(error, APIError):
            # Check for specific API error codes
            if hasattr(error, 'status_code'):
                if error.status_code == 429:
                    return "rate_limit"
                elif error.status_code >= 500:
                    return "server_error"
                elif error.status_code == 401:
                    return "auth_error"
                elif error.status_code == 400:
                    return "client_error"
            return "api_error"
        elif "timeout" in str(error).lower():
            return "timeout"
        elif "connection" in str(error).lower():
            return "connection_error"
        else:
            return "unknown_error"
    
    def _is_retriable_error(self, error_type: str) -> bool:
        """
        Determine if an error type is retriable.
        
        Args:
            error_type: Error type string
            
        Returns:
            True if error is retriable, False otherwise
        """
        retriable_errors = {
            "rate_limit", "timeout", "server_error", "connection_error", "unknown_error"
        }
        return error_type in retriable_errors
    
    async def _apply_retry_delay(self, attempt: int) -> None:
        """
        Apply exponential backoff delay before retry.
        
        Args:
            attempt: Current attempt number (0-based)
        """
        delay = self.retry_strategy.get_delay(attempt)
        if delay > 0:
            self.logger.debug(f"Applying retry delay: {delay:.2f}s")
            await asyncio.sleep(delay)
    
    async def _handle_rate_limit_error(self, error: Exception) -> None:
        """
        Handle rate limit errors by updating rate limit state.
        
        Args:
            error: Rate limit error
        """
        # Extract retry-after header if available
        retry_after = 60.0  # Default to 60 seconds
        
        if hasattr(error, 'response') and error.response:
            headers = getattr(error.response, 'headers', {})
            if 'retry-after' in headers:
                try:
                    retry_after = float(headers['retry-after'])
                except (ValueError, TypeError):
                    pass
        
        self._rate_limit_delay = retry_after
        self._last_rate_limit_time = time.time()
        
        self.logger.warning(f"Rate limit hit, will delay requests by {retry_after}s")
    
    async def _apply_rate_limit_delay(self) -> None:
        """Apply rate limiting delay if needed."""
        if self._rate_limit_delay > 0:
            elapsed = time.time() - self._last_rate_limit_time
            remaining_delay = self._rate_limit_delay - elapsed
            
            if remaining_delay > 0:
                self.logger.debug(f"Applying rate limit delay: {remaining_delay:.2f}s")
                await asyncio.sleep(remaining_delay)
            else:
                # Reset rate limit state
                self._rate_limit_delay = 0.0
                self._last_rate_limit_time = 0.0
    
    def get_retry_strategy(self) -> RetryStrategy:
        """Get the current retry strategy."""
        return self.retry_strategy
    
    def set_retry_strategy(self, retry_strategy: RetryStrategy) -> None:
        """
        Set a new retry strategy.
        
        Args:
            retry_strategy: New retry strategy configuration
        """
        self.retry_strategy = retry_strategy
        self.logger.info(f"Retry strategy updated: max_retries={retry_strategy.max_retries}")
    
    def get_translation_statistics(self, results: List[TranslationResult]) -> Dict[str, Any]:
        """
        Generate detailed statistics from translation results.
        
        Args:
            results: List of translation results
            
        Returns:
            Dictionary with detailed statistics
        """
        if not results:
            return {}
        
        total_results = len(results)
        successful = sum(1 for r in results if r.success)
        failed = total_results - successful
        
        total_retries = sum(r.retry_count for r in results)
        total_time = sum(r.processing_time for r in results)
        
        avg_time = total_time / total_results if total_results > 0 else 0
        avg_retries = total_retries / total_results if total_results > 0 else 0
        
        # Error analysis
        error_types = {}
        for result in results:
            if not result.success and result.error_message:
                error_type = "validation_error" if "validation" in result.error_message.lower() else "api_error"
                error_types[error_type] = error_types.get(error_type, 0) + 1
        
        return {
            "total_chunks": total_results,
            "successful_translations": successful,
            "failed_translations": failed,
            "success_rate": (successful / total_results * 100) if total_results > 0 else 0,
            "total_retries": total_retries,
            "average_retries_per_chunk": avg_retries,
            "total_processing_time": total_time,
            "average_processing_time": avg_time,
            "error_breakdown": error_types
        }
