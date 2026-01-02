"""
Main translation engine that orchestrates the entire translation workflow.

This module provides the TranslationEngine class that coordinates all components
to perform complete Markdown file translation with progress tracking and error recovery.
"""

import asyncio
import logging
import time
import json
import os
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

from .interfaces import (
    ISplitter, ITranslator, IValidator, IMerger, 
    IConfigManager, ILogger, IProgressReporter
)
from .models import (
    FileChunk, TranslationResult, TranslationProgress, 
    TranslationStats, MergeResult, TranslationStatus
)
from .config import ConfigManager
from .splitter import MarkdownSplitter
from .translator import TranslationPool
from .validator import IntegrityValidator
from .merger import ContentMerger
from .progress import RichProgressReporter
from .logging_config import setup_logging
from .performance import PerformanceMonitor, PerformanceOptimizer
from .security import SecurityManager


class TranslationEngine:
    """
    Main translation engine that orchestrates the complete translation workflow.
    
    This class integrates all components to provide:
    - Complete file translation workflow
    - Progress tracking and reporting
    - Error handling and recovery
    - Checkpoint creation and restoration
    - Statistics generation
    """
    
    def __init__(self, 
                 config_manager: Optional[IConfigManager] = None,
                 splitter: Optional[ISplitter] = None,
                 translator: Optional[ITranslator] = None,
                 validator: Optional[IValidator] = None,
                 merger: Optional[IMerger] = None,
                 progress_reporter: Optional[IProgressReporter] = None,
                 performance_monitor: Optional[PerformanceMonitor] = None,
                 security_manager: Optional[SecurityManager] = None,
                 logger: Optional[logging.Logger] = None):
        """
        Initialize the translation engine with all required components.
        
        Args:
            config_manager: Configuration manager (creates default if None)
            splitter: File splitter (creates default if None)
            translator: Translation service (creates default if None)
            validator: Content validator (creates default if None)
            merger: Content merger (creates default if None)
            progress_reporter: Progress reporter (creates default if None)
            performance_monitor: Performance monitoring (creates default if None)
            security_manager: Security manager (creates default if None)
            logger: Logger instance (creates default if None)
        """
        # Initialize logger first
        self.logger = logger or logging.getLogger(__name__)
        
        # Initialize or use provided components
        self.config_manager = config_manager or ConfigManager()
        self.validator = validator or IntegrityValidator()
        self.merger = merger or ContentMerger(logger=self.logger)
        self.progress_reporter = progress_reporter or RichProgressReporter()
        
        # Initialize performance monitoring and security
        self.performance_monitor = performance_monitor or PerformanceMonitor()
        self.security_manager = security_manager or SecurityManager()
        self.performance_optimizer = PerformanceOptimizer(self.performance_monitor)
        
        # Initialize splitter with default chunk size
        self.splitter = splitter or MarkdownSplitter(chunk_size=500)
        
        # Initialize translator with API client, validator, performance monitor, and security
        if translator:
            self.translator = translator
        else:
            api_client = self.config_manager.get_api_client()
            self.translator = TranslationPool(
                concurrency=5,
                api_client=api_client,
                validator=self.validator,
                performance_monitor=self.performance_monitor,
                security_manager=self.security_manager
            )
        
        # Translation state
        self.current_progress: Optional[TranslationProgress] = None
        self.checkpoint_dir = Path(".translation_checkpoints")
        
        self.logger.info("Translation engine initialized with performance monitoring and security")
    
    async def translate_file(self, 
                           input_path: str, 
                           output_path: str,
                           chunk_size: Optional[int] = None,
                           concurrency: Optional[int] = None,
                           progress_callback: Optional[Callable[[TranslationProgress], None]] = None) -> TranslationStats:
        """
        Translate a complete Markdown file.
        
        Args:
            input_path: Path to input Markdown file
            output_path: Path for output translated file
            chunk_size: Optional chunk size override
            concurrency: Optional concurrency override
            progress_callback: Optional callback for progress updates
            
        Returns:
            TranslationStats with complete translation statistics
            
        Raises:
            FileNotFoundError: If input file doesn't exist
            ValueError: If configuration is invalid
            Exception: For other translation errors
        """
        start_time = time.time()
        
        try:
            self.logger.info(f"开始翻译文件: {input_path} -> {output_path}")
            
            # Start performance monitoring
            self.performance_monitor.start_monitoring()
            
            # Security validation of inputs
            input_validation = self.security_manager.validate_file_path(input_path)
            if not input_validation.is_valid and input_validation.risk_level in ['high', 'critical']:
                raise ValueError(f"Input file security validation failed: {', '.join(input_validation.issues)}")
            
            output_validation = self.security_manager.validate_output_path(output_path)
            if not output_validation.is_valid and output_validation.risk_level in ['high', 'critical']:
                raise ValueError(f"Output path security validation failed: {', '.join(output_validation.issues)}")
            
            # Validate inputs
            self._validate_translation_inputs(input_path, output_path)
            
            # Configure components if overrides provided
            if chunk_size is not None:
                # User manually specified chunk size - use it directly without optimization
                self.splitter.set_chunk_size(chunk_size)
                self.logger.info(f"使用用户指定的分块大小: {chunk_size} (跳过优化器)")
            else:
                # No chunk size specified - use optimizer to suggest optimal size
                current_chunk_size = self.splitter.get_chunk_size()
                optimal_chunk_size = self.performance_optimizer.suggest_optimal_chunk_size(current_chunk_size)
                if optimal_chunk_size != current_chunk_size:
                    self.logger.info(f"Performance optimizer suggests chunk size: {optimal_chunk_size} (current: {current_chunk_size})")
                    self.splitter.set_chunk_size(optimal_chunk_size)
                    self.logger.info(f"设置优化后的分块大小: {optimal_chunk_size}")
            
            if concurrency is not None:
                # User manually specified concurrency - use it directly without optimization
                self.translator.set_concurrency(concurrency)
                self.logger.info(f"使用用户指定的并发度: {concurrency} (跳过优化器)")
            else:
                # No concurrency specified - use optimizer to suggest optimal concurrency
                current_concurrency = self.translator.get_concurrency()
                optimal_concurrency = self.performance_optimizer.suggest_optimal_concurrency(current_concurrency)
                if optimal_concurrency != current_concurrency:
                    self.logger.info(f"Performance optimizer suggests concurrency: {optimal_concurrency} (current: {current_concurrency})")
                    self.translator.set_concurrency(optimal_concurrency)
                    self.logger.info(f"设置优化后的并发度: {optimal_concurrency}")
            
            # Step 1: Split file into chunks
            self.logger.info("步骤 1: 分割文件")
            chunks = await self._split_file_with_progress(input_path)
            
            if not chunks:
                raise ValueError("文件分割后没有生成任何片段")
            
            # Initialize progress tracking
            self.current_progress = TranslationProgress(
                completed_chunks=0,
                total_chunks=len(chunks),
                start_time=start_time
            )
            
            # Start progress reporting
            self.progress_reporter.start_progress(
                total_items=len(chunks),
                description="翻译Markdown片段"
            )
            
            # Step 2: Translate chunks with performance monitoring
            self.logger.info(f"步骤 2: 翻译 {len(chunks)} 个片段")
            
            # Check if processing should be paused due to resource constraints
            if self.performance_optimizer.should_pause_processing():
                self.logger.warning("Resource constraints detected, pausing briefly...")
                await asyncio.sleep(5)
            
            translation_start_time = time.time()
            translation_results = await self._translate_chunks_with_progress(
                chunks, progress_callback
            )
            translation_duration = time.time() - translation_start_time
            
            # Record throughput
            if translation_duration > 0:
                self.performance_monitor.record_throughput(len(chunks), translation_duration)
            
            # Step 3: Merge results
            self.logger.info("步骤 3: 合并翻译结果")
            merge_result = await self._merge_results_with_progress(
                translation_results, output_path
            )
            
            # Step 4: Generate statistics
            stats = self.merger.generate_statistics(translation_results)
            stats.total_processing_time = time.time() - start_time
            
            # Finish progress reporting
            success = merge_result.success and stats.failed_translations == 0
            self.progress_reporter.finish_progress(
                success=success,
                message=f"翻译完成: {stats.successful_translations}/{stats.total_chunks} 成功"
            )
            
            # Clean up with security
            await self._cleanup_translation(chunks)
            
            # Stop performance monitoring and generate report
            self.performance_monitor.stop_monitoring()
            self.performance_monitor.log_performance_summary()
            
            # Security cleanup
            self.security_manager.cleanup_temp_files()
            
            self.logger.info(f"翻译完成: 总耗时 {stats.total_processing_time:.2f}秒")
            return stats
            
        except Exception as e:
            self.logger.error(f"翻译过程中发生错误: {str(e)}", exc_info=True)
            
            # Stop monitoring and cleanup on error
            self.performance_monitor.stop_monitoring()
            self.security_manager.cleanup_temp_files()
            
            # Finish progress with error
            self.progress_reporter.finish_progress(
                success=False,
                message=f"翻译失败: {str(e)}"
            )
            
            raise
    
    async def resume_translation(self, checkpoint_path: str) -> TranslationStats:
        """
        Resume translation from a checkpoint.
        
        Args:
            checkpoint_path: Path to checkpoint file
            
        Returns:
            TranslationStats with complete translation statistics
        """
        self.logger.info(f"从检查点恢复翻译: {checkpoint_path}")
        
        try:
            # Load checkpoint
            progress = self._load_checkpoint(checkpoint_path)
            
            # Resume translation logic would go here
            # For now, this is a placeholder for the checkpoint functionality
            
            raise NotImplementedError("检查点恢复功能尚未实现")
            
        except Exception as e:
            self.logger.error(f"恢复翻译失败: {str(e)}", exc_info=True)
            raise
    
    def create_checkpoint(self, progress: TranslationProgress, checkpoint_name: str = None) -> str:
        """
        Create a checkpoint of current translation progress.
        
        Args:
            progress: Current translation progress
            checkpoint_name: Optional checkpoint name
            
        Returns:
            Path to created checkpoint file
        """
        if not checkpoint_name:
            timestamp = int(time.time())
            checkpoint_name = f"translation_checkpoint_{timestamp}.json"
        
        # Ensure checkpoint directory exists
        self.checkpoint_dir.mkdir(exist_ok=True)
        
        checkpoint_path = self.checkpoint_dir / checkpoint_name
        
        # Serialize progress to JSON
        checkpoint_data = {
            "completed_chunks": progress.completed_chunks,
            "total_chunks": progress.total_chunks,
            "current_chunk_id": progress.current_chunk_id,
            "start_time": progress.start_time,
            "estimated_completion": progress.estimated_completion,
            "errors": progress.errors,
            "timestamp": time.time()
        }
        
        try:
            with open(checkpoint_path, 'w', encoding='utf-8') as f:
                json.dump(checkpoint_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"检查点已创建: {checkpoint_path}")
            return str(checkpoint_path)
            
        except Exception as e:
            self.logger.error(f"创建检查点失败: {str(e)}")
            raise
    
    def _load_checkpoint(self, checkpoint_path: str) -> TranslationProgress:
        """
        Load translation progress from checkpoint file.
        
        Args:
            checkpoint_path: Path to checkpoint file
            
        Returns:
            TranslationProgress object
        """
        try:
            with open(checkpoint_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return TranslationProgress(
                completed_chunks=data["completed_chunks"],
                total_chunks=data["total_chunks"],
                current_chunk_id=data.get("current_chunk_id"),
                start_time=data.get("start_time"),
                estimated_completion=data.get("estimated_completion"),
                errors=data.get("errors", [])
            )
            
        except Exception as e:
            self.logger.error(f"加载检查点失败: {str(e)}")
            raise
    
    def _validate_translation_inputs(self, input_path: str, output_path: str) -> None:
        """
        Validate translation input parameters.
        
        Args:
            input_path: Input file path
            output_path: Output file path
            
        Raises:
            FileNotFoundError: If input file doesn't exist
            ValueError: If paths are invalid
        """
        # Check input file exists
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"输入文件不存在: {input_path}")
        
        # Check input file is readable
        if not os.access(input_path, os.R_OK):
            raise ValueError(f"输入文件不可读: {input_path}")
        
        # Check output directory is writable
        output_dir = Path(output_path).parent
        if not output_dir.exists():
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise ValueError(f"无法创建输出目录: {output_dir}, 错误: {e}")
        
        # Validate API configuration
        if not self.config_manager.validate_api_config():
            raise ValueError("API配置无效，请检查环境变量设置")
    
    async def _split_file_with_progress(self, input_path: str) -> List[FileChunk]:
        """
        Split file with progress reporting.
        
        Args:
            input_path: Path to input file
            
        Returns:
            List of FileChunk objects
        """
        try:
            # Run splitter in thread pool to avoid blocking
            chunks = await asyncio.to_thread(self.splitter.split_file, input_path)
            
            self.logger.info(f"文件分割完成: {len(chunks)} 个片段")
            return chunks
            
        except Exception as e:
            self.logger.error(f"文件分割失败: {str(e)}")
            raise
    
    async def _translate_chunks_with_progress(self, 
                                           chunks: List[FileChunk],
                                           progress_callback: Optional[Callable[[TranslationProgress], None]] = None) -> List[TranslationResult]:
        """
        Translate chunks with progress tracking.
        
        Args:
            chunks: List of chunks to translate
            progress_callback: Optional progress callback
            
        Returns:
            List of TranslationResult objects
        """
        try:
            # Create progress tracking wrapper
            async def progress_wrapper():
                # Start translation
                task = asyncio.create_task(self.translator.translate_chunks(chunks))
                
                # Monitor progress
                while not task.done():
                    await asyncio.sleep(1)  # Check every second
                    
                    # Update progress (this is a simplified version)
                    if self.current_progress and progress_callback:
                        progress_callback(self.current_progress)
                    
                    # Update progress reporter
                    completed = self.current_progress.completed_chunks if self.current_progress else 0
                    self.progress_reporter.update_progress(
                        completed=completed,
                        message=f"已完成 {completed}/{len(chunks)} 个片段"
                    )
                
                return await task
            
            results = await progress_wrapper()
            
            self.logger.info(f"翻译完成: {sum(1 for r in results if r.success)}/{len(results)} 成功")
            return results
            
        except Exception as e:
            self.logger.error(f"翻译过程失败: {str(e)}")
            raise
    
    async def _merge_results_with_progress(self, 
                                         results: List[TranslationResult], 
                                         output_path: str) -> MergeResult:
        """
        Merge translation results with progress reporting.
        
        Args:
            results: Translation results to merge
            output_path: Output file path
            
        Returns:
            MergeResult object
        """
        try:
            # Run merger in thread pool
            merge_result = await asyncio.to_thread(
                self.merger.merge_translations, 
                results, 
                output_path
            )
            
            if merge_result.success:
                self.logger.info(f"合并成功: {merge_result.chunks_merged} 个片段合并到 {output_path}")
            else:
                self.logger.error(f"合并失败: {len(merge_result.errors)} 个错误")
                for error in merge_result.errors:
                    self.logger.error(f"  - {error}")
            
            return merge_result
            
        except Exception as e:
            self.logger.error(f"合并过程失败: {str(e)}")
            raise
    
    async def _cleanup_translation(self, chunks: List[FileChunk]) -> None:
        """
        Clean up temporary files and resources.
        
        Args:
            chunks: List of chunks that may have temporary files
        """
        try:
            # Collect temporary files
            temp_files = []
            for chunk in chunks:
                if chunk.temp_file and os.path.exists(chunk.temp_file):
                    temp_files.append(chunk.temp_file)
            
            # Clean up temporary files
            if temp_files:
                await asyncio.to_thread(self.merger.cleanup_temp_files, temp_files)
            
            self.logger.debug("清理完成")
            
        except Exception as e:
            self.logger.warning(f"清理过程中出现错误: {str(e)}")
    
    def get_translation_progress(self) -> Optional[TranslationProgress]:
        """
        Get current translation progress.
        
        Returns:
            Current TranslationProgress or None if no translation in progress
        """
        return self.current_progress
    
    def set_chunk_size(self, chunk_size: int) -> None:
        """
        Set the chunk size for file splitting.
        
        Args:
            chunk_size: New chunk size
        """
        self.splitter.set_chunk_size(chunk_size)
        self.logger.info(f"分块大小设置为: {chunk_size}")
    
    def set_concurrency(self, concurrency: int) -> None:
        """
        Set the concurrency level for translation.
        
        Args:
            concurrency: New concurrency level
        """
        self.translator.set_concurrency(concurrency)
        self.logger.info(f"并发度设置为: {concurrency}")
    
    def get_engine_statistics(self) -> Dict[str, Any]:
        """
        Get engine configuration and statistics.
        
        Returns:
            Dictionary with engine information
        """
        return {
            "chunk_size": self.splitter.get_chunk_size(),
            "concurrency": self.translator.get_concurrency(),
            "api_base_url": self.config_manager.get_config_value("TRANSLATE_API"),
            "model_name": self.config_manager.get_config_value("TRANSLATE_MODEL"),
            "current_progress": self.current_progress.completion_percentage if self.current_progress else 0
        }


def create_translation_engine(chunk_size: int = 500, 
                            concurrency: int = 5,
                            verbose: bool = False) -> TranslationEngine:
    """
    Factory function to create a configured TranslationEngine.
    
    Args:
        chunk_size: Chunk size for file splitting
        concurrency: Concurrency level for translation
        verbose: Enable verbose logging
        
    Returns:
        Configured TranslationEngine instance
    """
    # Setup logging
    logger = setup_logging(verbose=verbose)
    
    # Create components
    config_manager = ConfigManager()
    splitter = MarkdownSplitter(chunk_size=chunk_size)
    validator = IntegrityValidator()
    merger = ContentMerger(logger=logger)
    progress_reporter = RichProgressReporter()
    
    # Create performance monitoring and security components
    performance_monitor = PerformanceMonitor()
    security_manager = SecurityManager()
    
    # Create translator with API client, performance monitor, and security
    api_client = config_manager.get_api_client()
    translator = TranslationPool(
        concurrency=concurrency,
        api_client=api_client,
        validator=validator,
        performance_monitor=performance_monitor,
        security_manager=security_manager
    )
    
    # Create engine
    engine = TranslationEngine(
        config_manager=config_manager,
        splitter=splitter,
        translator=translator,
        validator=validator,
        merger=merger,
        progress_reporter=progress_reporter,
        performance_monitor=performance_monitor,
        security_manager=security_manager,
        logger=logger
    )
    
    return engine
