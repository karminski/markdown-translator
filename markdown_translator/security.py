"""
Security utilities for the Markdown translator.

This module provides security features including input validation, path security checks,
sensitive data handling, and secure temporary file management.
"""

import os
import re
import tempfile
import hashlib
import secrets
from pathlib import Path
from typing import List, Dict, Optional, Any, Union
from dataclasses import dataclass
import logging


@dataclass
class SecurityValidationResult:
    """Result of security validation."""
    is_valid: bool
    issues: List[str]
    risk_level: str  # 'low', 'medium', 'high', 'critical'
    
    def __post_init__(self):
        if self.issues is None:
            self.issues = []


class SecurityManager:
    """
    Security manager for the Markdown translator.
    
    Provides comprehensive security features including input validation,
    path security, sensitive data handling, and secure file operations.
    """
    
    # Dangerous file extensions that should not be processed
    DANGEROUS_EXTENSIONS = {
        '.exe', '.bat', '.cmd', '.com', '.scr', '.pif', '.vbs', '.js', '.jar',
        '.dll', '.sys', '.bin', '.msi', '.deb', '.rpm', '.dmg', '.pkg'
    }
    
    # Allowed file extensions for processing
    ALLOWED_EXTENSIONS = {
        '.md', '.markdown', '.txt', '.text'
    }
    
    # Patterns that might indicate malicious content
    SUSPICIOUS_PATTERNS = [
        r'<script[^>]*>.*?</script>',  # JavaScript
        r'javascript:',               # JavaScript URLs
        r'data:.*base64',            # Base64 data URLs
        r'vbscript:',                # VBScript
        r'file:///',                 # Local file URLs
        r'\\\\[^\\]+\\',            # UNC paths
        r'\.\.[\\/]',               # Path traversal
        r'[<>"|*?]',                # Invalid filename characters
    ]
    
    # Sensitive data patterns to sanitize from logs
    SENSITIVE_PATTERNS = [
        r'(?i)(api[_-]?key|token|password|secret)["\s]*[:=]["\s]*([^\s"]+)',
        r'(?i)(bearer\s+)([a-zA-Z0-9\-._~+/]+=*)',
        r'(?i)(authorization["\s]*:["\s]*)(.*)',
    ]
    
    def __init__(self):
        """Initialize the security manager."""
        self.logger = logging.getLogger(__name__)
        self._temp_files: List[str] = []
        self._secure_random = secrets.SystemRandom()
    
    def validate_file_path(self, file_path: Union[str, Path]) -> SecurityValidationResult:
        """
        Validate that a file path is safe to process.
        
        Args:
            file_path: Path to validate
            
        Returns:
            SecurityValidationResult indicating if the path is safe
        """
        issues = []
        risk_level = 'low'
        
        try:
            path = Path(file_path).resolve()
            
            # Check if file exists
            if not path.exists():
                issues.append(f"File does not exist: {path}")
                risk_level = 'medium'
            
            # Check if it's actually a file
            if path.exists() and not path.is_file():
                issues.append(f"Path is not a file: {path}")
                risk_level = 'medium'
            
            # Check file extension
            if path.suffix.lower() not in self.ALLOWED_EXTENSIONS:
                if path.suffix.lower() in self.DANGEROUS_EXTENSIONS:
                    issues.append(f"Dangerous file extension: {path.suffix}")
                    risk_level = 'critical'
                else:
                    issues.append(f"Unsupported file extension: {path.suffix}")
                    risk_level = 'medium'
            
            # Check for path traversal attempts
            path_str = str(path)
            if '..' in path_str or path_str.startswith('/'):
                issues.append("Potential path traversal detected")
                risk_level = 'low'
            
            # Check file size (prevent processing extremely large files)
            if path.exists():
                file_size = path.stat().st_size
                max_size = 100 * 1024 * 1024  # 100MB limit
                if file_size > max_size:
                    issues.append(f"File too large: {file_size / 1024 / 1024:.1f}MB (max: {max_size / 1024 / 1024}MB)")
                    risk_level = 'high'
            
            # Check file permissions
            if path.exists() and not os.access(path, os.R_OK):
                issues.append("File is not readable")
                risk_level = 'medium'
            
        except Exception as e:
            issues.append(f"Error validating path: {str(e)}")
            risk_level = 'high'
        
        is_valid = len(issues) == 0 or risk_level == 'low'
        
        return SecurityValidationResult(
            is_valid=is_valid,
            issues=issues,
            risk_level=risk_level
        )
    
    def validate_output_path(self, output_path: Union[str, Path]) -> SecurityValidationResult:
        """
        Validate that an output path is safe to write to.
        
        Args:
            output_path: Output path to validate
            
        Returns:
            SecurityValidationResult indicating if the path is safe
        """
        issues = []
        risk_level = 'low'
        
        try:
            path = Path(output_path).resolve()
            
            # Check parent directory exists and is writable
            parent_dir = path.parent
            if not parent_dir.exists():
                try:
                    parent_dir.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    issues.append(f"Cannot create parent directory: {e}")
                    risk_level = 'high'
            
            if parent_dir.exists() and not os.access(parent_dir, os.W_OK):
                issues.append("Parent directory is not writable")
                risk_level = 'high'
            
            # Check if file already exists and is writable
            if path.exists() and not os.access(path, os.W_OK):
                issues.append("Output file exists but is not writable")
                risk_level = 'medium'
            
            # Check for dangerous file extensions
            if path.suffix.lower() in self.DANGEROUS_EXTENSIONS:
                issues.append(f"Dangerous output file extension: {path.suffix}")
                risk_level = 'critical'
            
            # Check for path traversal
            path_str = str(path)
            if '..' in path_str:
                issues.append("Potential path traversal in output path")
                risk_level = 'high'
            
        except Exception as e:
            issues.append(f"Error validating output path: {str(e)}")
            risk_level = 'high'
        
        is_valid = len(issues) == 0 or risk_level == 'low'
        
        return SecurityValidationResult(
            is_valid=is_valid,
            issues=issues,
            risk_level=risk_level
        )
    
    def validate_content(self, content: str) -> SecurityValidationResult:
        """
        Validate content for potential security issues.
        
        Args:
            content: Content to validate
            
        Returns:
            SecurityValidationResult indicating if content is safe
        """
        issues = []
        risk_level = 'low'
        
        # Check for suspicious patterns
        for pattern in self.SUSPICIOUS_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
            if matches:
                issues.append(f"Suspicious pattern detected: {pattern}")
                risk_level = 'medium'
        
        # Check content length
        if len(content) > 10 * 1024 * 1024:  # 10MB text limit
            issues.append("Content is extremely large")
            risk_level = 'medium'
        
        # Check for binary content
        try:
            content.encode('utf-8')
        except UnicodeEncodeError:
            issues.append("Content contains non-UTF-8 characters")
            risk_level = 'medium'
        
        # Check for null bytes (potential binary content)
        if '\x00' in content:
            issues.append("Content contains null bytes (potential binary data)")
            risk_level = 'high'
        
        is_valid = risk_level in ['low', 'medium']
        
        return SecurityValidationResult(
            is_valid=is_valid,
            issues=issues,
            risk_level=risk_level
        )
    
    def sanitize_log_content(self, content: str) -> str:
        """
        Remove sensitive information from content before logging.
        
        Args:
            content: Content to sanitize
            
        Returns:
            Sanitized content safe for logging
        """
        sanitized = content
        
        # Replace sensitive patterns
        for pattern in self.SENSITIVE_PATTERNS:
            sanitized = re.sub(pattern, r'\1[REDACTED]', sanitized, flags=re.IGNORECASE)
        
        # Truncate very long content
        max_log_length = 1000
        if len(sanitized) > max_log_length:
            sanitized = sanitized[:max_log_length] + '... [TRUNCATED]'
        
        return sanitized
    
    def create_secure_temp_file(self, content: str, suffix: str = '.tmp') -> str:
        """
        Create a secure temporary file with the given content.
        
        Args:
            content: Content to write to the temporary file
            suffix: File suffix for the temporary file
            
        Returns:
            Path to the created temporary file
        """
        try:
            # Create temporary file with secure permissions
            fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix='mdtrans_')
            
            # Set restrictive permissions (owner read/write only)
            os.chmod(temp_path, 0o600)
            
            # Write content
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Track for cleanup
            self._temp_files.append(temp_path)
            
            self.logger.debug(f"Created secure temporary file: {temp_path}")
            return temp_path
            
        except Exception as e:
            self.logger.error(f"Error creating secure temporary file: {e}")
            raise
    
    def cleanup_temp_files(self) -> None:
        """Clean up all tracked temporary files securely."""
        for temp_file in self._temp_files[:]:  # Copy list to avoid modification during iteration
            try:
                if os.path.exists(temp_file):
                    # Overwrite file content before deletion for security
                    self._secure_delete_file(temp_file)
                    self.logger.debug(f"Securely deleted temporary file: {temp_file}")
                
                self._temp_files.remove(temp_file)
                
            except Exception as e:
                self.logger.warning(f"Error cleaning up temporary file {temp_file}: {e}")
    
    def _secure_delete_file(self, file_path: str) -> None:
        """
        Securely delete a file by overwriting its content.
        
        Args:
            file_path: Path to the file to delete securely
        """
        try:
            # Get file size
            file_size = os.path.getsize(file_path)
            
            # Overwrite with random data multiple times
            with open(file_path, 'r+b') as f:
                for _ in range(3):  # 3 passes of random data
                    f.seek(0)
                    f.write(os.urandom(file_size))
                    f.flush()
                    os.fsync(f.fileno())
            
            # Finally delete the file
            os.remove(file_path)
            
        except Exception as e:
            self.logger.warning(f"Error in secure file deletion: {e}")
            # Fallback to regular deletion
            try:
                os.remove(file_path)
            except Exception:
                pass
    
    def validate_api_response(self, response_data: Dict[str, Any]) -> SecurityValidationResult:
        """
        Validate API response for security issues.
        
        Args:
            response_data: API response data to validate
            
        Returns:
            SecurityValidationResult indicating if response is safe
        """
        issues = []
        risk_level = 'low'
        
        try:
            # Check response structure
            if not isinstance(response_data, dict):
                issues.append("API response is not a dictionary")
                risk_level = 'medium'
                return SecurityValidationResult(False, issues, risk_level)
            
            # Check for expected fields
            if 'choices' not in response_data:
                issues.append("API response missing 'choices' field")
                risk_level = 'medium'
            
            # Validate content in choices
            choices = response_data.get('choices', [])
            for i, choice in enumerate(choices):
                if not isinstance(choice, dict):
                    issues.append(f"Choice {i} is not a dictionary")
                    risk_level = 'medium'
                    continue
                
                message = choice.get('message', {})
                content = message.get('content', '')
                
                if content:
                    content_validation = self.validate_content(content)
                    if not content_validation.is_valid:
                        issues.extend([f"Choice {i}: {issue}" for issue in content_validation.issues])
                        if content_validation.risk_level == 'high':
                            risk_level = 'high'
                        elif content_validation.risk_level == 'medium' and risk_level == 'low':
                            risk_level = 'medium'
            
        except Exception as e:
            issues.append(f"Error validating API response: {str(e)}")
            risk_level = 'high'
        
        is_valid = risk_level in ['low', 'medium']
        
        return SecurityValidationResult(
            is_valid=is_valid,
            issues=issues,
            risk_level=risk_level
        )
    
    def generate_secure_filename(self, base_name: str, extension: str = '.tmp') -> str:
        """
        Generate a secure filename with random components.
        
        Args:
            base_name: Base name for the file
            extension: File extension
            
        Returns:
            Secure filename
        """
        # Sanitize base name
        safe_base = re.sub(r'[^a-zA-Z0-9_-]', '_', base_name)
        
        # Add random component
        random_part = secrets.token_hex(8)
        
        # Combine parts
        secure_name = f"{safe_base}_{random_part}{extension}"
        
        return secure_name
    
    def hash_content(self, content: str) -> str:
        """
        Generate a secure hash of content for integrity checking.
        
        Args:
            content: Content to hash
            
        Returns:
            SHA-256 hash of the content
        """
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def validate_environment_variables(self, required_vars: List[str]) -> SecurityValidationResult:
        """
        Validate that required environment variables are set and secure.
        
        Args:
            required_vars: List of required environment variable names
            
        Returns:
            SecurityValidationResult indicating if environment is secure
        """
        issues = []
        risk_level = 'low'
        
        for var_name in required_vars:
            value = os.environ.get(var_name)
            
            if not value:
                issues.append(f"Required environment variable not set: {var_name}")
                risk_level = 'high'
                continue
            
            # Check for common insecure values
            insecure_values = ['test', 'demo', 'example', 'placeholder', '123456']
            if value.lower() in insecure_values:
                issues.append(f"Environment variable {var_name} has insecure value")
                risk_level = 'medium'
            
            # Check minimum length for tokens/keys
            if 'token' in var_name.lower() or 'key' in var_name.lower():
                if len(value) < 20:
                    issues.append(f"Environment variable {var_name} appears too short for a secure token")
                    risk_level = 'medium'
        
        is_valid = risk_level != 'high'
        
        return SecurityValidationResult(
            is_valid=is_valid,
            issues=issues,
            risk_level=risk_level
        )
    
    def create_security_report(self) -> Dict[str, Any]:
        """
        Create a comprehensive security report.
        
        Returns:
            Dictionary containing security status and recommendations
        """
        report = {
            'timestamp': os.time.time(),
            'temp_files_tracked': len(self._temp_files),
            'security_checks_performed': [],
            'recommendations': []
        }
        
        # Check environment security
        env_vars = ['TRANSLATE_API_TOKEN', 'TRANSLATE_API', 'TRANSLATE_MODEL']
        env_validation = self.validate_environment_variables(env_vars)
        report['environment_security'] = {
            'is_secure': env_validation.is_valid,
            'issues': env_validation.issues,
            'risk_level': env_validation.risk_level
        }
        
        # Add recommendations based on findings
        if not env_validation.is_valid:
            report['recommendations'].append("Review and secure environment variable configuration")
        
        if len(self._temp_files) > 10:
            report['recommendations'].append("Consider cleaning up temporary files more frequently")
        
        # Check file system permissions
        try:
            temp_dir = tempfile.gettempdir()
            temp_dir_stat = os.stat(temp_dir)
            if temp_dir_stat.st_mode & 0o077:  # Check if others have access
                report['recommendations'].append("Temporary directory has overly permissive permissions")
        except Exception:
            pass
        
        if not report['recommendations']:
            report['recommendations'].append("Security configuration looks good")
        
        return report


class InputValidator:
    """
    Input validation utilities for command-line arguments and user input.
    """
    
    def __init__(self):
        """Initialize the input validator."""
        self.logger = logging.getLogger(__name__)
    
    def validate_chunk_size(self, chunk_size: int) -> SecurityValidationResult:
        """
        Validate chunk size parameter.
        
        Args:
            chunk_size: Chunk size to validate
            
        Returns:
            SecurityValidationResult indicating if chunk size is valid
        """
        issues = []
        risk_level = 'low'
        
        if chunk_size < 10:
            issues.append("Chunk size too small (minimum: 10)")
            risk_level = 'medium'
        elif chunk_size > 10000:
            issues.append("Chunk size too large (maximum: 10000)")
            risk_level = 'medium'
        
        is_valid = len(issues) == 0
        
        return SecurityValidationResult(
            is_valid=is_valid,
            issues=issues,
            risk_level=risk_level
        )
    
    def validate_concurrency(self, concurrency: int) -> SecurityValidationResult:
        """
        Validate concurrency parameter.
        
        Args:
            concurrency: Concurrency level to validate
            
        Returns:
            SecurityValidationResult indicating if concurrency is valid
        """
        issues = []
        risk_level = 'low'
        
        if concurrency < 1:
            issues.append("Concurrency must be at least 1")
            risk_level = 'high'
        elif concurrency > 50:
            issues.append("Concurrency too high (maximum: 50)")
            risk_level = 'medium'
        
        is_valid = len(issues) == 0
        
        return SecurityValidationResult(
            is_valid=is_valid,
            issues=issues,
            risk_level=risk_level
        )
    
    def validate_cli_arguments(self, args: Dict[str, Any]) -> SecurityValidationResult:
        """
        Validate all CLI arguments for security issues.
        
        Args:
            args: Dictionary of CLI arguments
            
        Returns:
            SecurityValidationResult indicating if arguments are valid
        """
        issues = []
        risk_level = 'low'
        
        # Validate input file
        if 'input' in args and args['input']:
            security_manager = SecurityManager()
            input_validation = security_manager.validate_file_path(args['input'])
            if not input_validation.is_valid:
                issues.extend([f"Input file: {issue}" for issue in input_validation.issues])
                if input_validation.risk_level == 'high':
                    risk_level = 'high'
                elif input_validation.risk_level == 'medium' and risk_level == 'low':
                    risk_level = 'medium'
        
        # Validate output file
        if 'output' in args and args['output']:
            security_manager = SecurityManager()
            output_validation = security_manager.validate_output_path(args['output'])
            if not output_validation.is_valid:
                issues.extend([f"Output file: {issue}" for issue in output_validation.issues])
                if output_validation.risk_level == 'high':
                    risk_level = 'high'
                elif output_validation.risk_level == 'medium' and risk_level == 'low':
                    risk_level = 'medium'
        
        # Validate chunk size
        if 'chunk_size' in args and args['chunk_size']:
            chunk_validation = self.validate_chunk_size(args['chunk_size'])
            if not chunk_validation.is_valid:
                issues.extend(chunk_validation.issues)
                if chunk_validation.risk_level == 'medium' and risk_level == 'low':
                    risk_level = 'medium'
        
        # Validate concurrency
        if 'concurrency' in args and args['concurrency']:
            concurrency_validation = self.validate_concurrency(args['concurrency'])
            if not concurrency_validation.is_valid:
                issues.extend(concurrency_validation.issues)
                if concurrency_validation.risk_level == 'high':
                    risk_level = 'high'
                elif concurrency_validation.risk_level == 'medium' and risk_level == 'low':
                    risk_level = 'medium'
        
        is_valid = risk_level != 'high'
        
        return SecurityValidationResult(
            is_valid=is_valid,
            issues=issues,
            risk_level=risk_level
        )
