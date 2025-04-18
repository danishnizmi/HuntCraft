#!/usr/bin/env python3
"""
Sanitizer Module for Malware Detonation Platform
------------------------------------------------

This module provides utilities for safely handling, sanitizing, and processing
malware samples and their metadata to prevent security issues.
"""

import os
import re
import json
import logging
import hashlib
import base64
from pathlib import Path
from typing import Dict, List, Any, Union, Optional, Tuple

# Configure logging
logger = logging.getLogger(__name__)

# Constants
ALLOWED_EXTENSIONS = {'exe', 'dll', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'js', 'vbs', 'ps1', 
                     'bat', 'cmd', 'jar', 'apk', 'elf', 'zip', 'rar', '7z', 'tar', 'gz'}

class MalwareSanitizer:
    """Class for handling sanitization of malware samples and metadata."""
    
    def __init__(self, upload_dir: str, max_file_size_mb: int = 100, strict_mode: bool = True):
        """
        Initialize the sanitizer with configuration settings.
        
        Args:
            upload_dir: Directory where sanitized files will be stored
            max_file_size_mb: Maximum allowed file size in MB
            strict_mode: If True, enforce stricter validation
        """
        self.upload_dir = Path(upload_dir)
        self.max_file_size = max_file_size_mb * 1024 * 1024  # Convert to bytes
        self.strict_mode = strict_mode
        
        # Ensure upload directory exists
        os.makedirs(self.upload_dir, exist_ok=True)
        
        logger.info(f"Initialized MalwareSanitizer with upload_dir={upload_dir}, "
                   f"max_file_size={max_file_size_mb}MB, strict_mode={strict_mode}")
    
    def validate_file(self, file_path: Union[str, Path]) -> Tuple[bool, str]:
        """
        Validate if a file is safe to process.
        
        Args:
            file_path: Path to the file to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        file_path = Path(file_path)
        
        # Check if file exists
        if not file_path.exists():
            return False, "File does not exist"
        
        # Check file size
        file_size = file_path.stat().st_size
        if file_size > self.max_file_size:
            return False, f"File size ({file_size} bytes) exceeds maximum allowed size ({self.max_file_size} bytes)"
        
        # Check file extension
        if self.strict_mode and file_path.suffix.lstrip('.').lower() not in ALLOWED_EXTENSIONS:
            return False, f"File extension {file_path.suffix} is not allowed"
        
        return True, ""
    
    def sanitize_filename(self, filename: str) -> str:
        """
        Sanitize a filename to prevent path traversal and other issues.
        
        Args:
            filename: Original filename
            
        Returns:
            Sanitized filename
        """
        # Remove path components
        filename = os.path.basename(filename)
        
        # Replace potentially dangerous characters
        filename = re.sub(r'[^\w\.-]', '_', filename)
        
        # Ensure filename isn't empty after sanitization
        if not filename:
            filename = "unnamed_file"
        
        logger.debug(f"Sanitized filename from {filename} to {filename}")
        return filename
    
    def sanitize_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize metadata associated with a malware sample.
        
        Args:
            metadata: Dictionary containing metadata
            
        Returns:
            Sanitized metadata dictionary
        """
        sanitized = {}
        
        # List of fields that should be sanitized as plain text
        text_fields = ['name', 'description', 'tags', 'source', 'type']
        
        # List of fields that should contain only alphanumeric and limited punctuation
        alphanumeric_fields = ['sha256', 'md5', 'sha1']
        
        # Process all fields
        for key, value in metadata.items():
            # Skip None values
            if value is None:
                sanitized[key] = None
                continue
            
            # Handle text fields
            if key in text_fields:
                # Sanitize text fields - strip HTML and limit length
                if isinstance(value, str):
                    # Strip HTML tags
                    value = re.sub(r'<[^>]+>', '', value)
                    # Limit length
                    max_length = 1000 if key == 'description' else 100
                    sanitized[key] = value[:max_length]
            
            # Handle hash fields
            elif key in alphanumeric_fields:
                if isinstance(value, str):
                    # Ensure it only contains valid hash characters
                    if re.match(r'^[a-fA-F0-9]+$', value):
                        sanitized[key] = value.lower()
                    else:
                        sanitized[key] = None
                        logger.warning(f"Invalid hash value for {key}: {value}")
            
            # Handle numeric fields
            elif key == 'file_size':
                try:
                    sanitized[key] = int(value)
                except (ValueError, TypeError):
                    sanitized[key] = 0
                    logger.warning(f"Invalid file size value: {value}")
            
            # Pass through other fields, but convert to string for safety
            else:
                if isinstance(value, (dict, list)):
                    # For complex structures, use json to ensure they're valid
                    try:
                        json_str = json.dumps(value)
                        sanitized[key] = json.loads(json_str)
                    except (TypeError, json.JSONDecodeError):
                        sanitized[key] = str(value)
                else:
                    sanitized[key] = str(value)
        
        logger.debug(f"Sanitized metadata: {sanitized}")
        return sanitized
    
    def safe_store_file(self, source_path: Union[str, Path], sha256_hash: str) -> Tuple[bool, str, Optional[Path]]:
        """
        Safely store a file using its hash as the filename.
        
        Args:
            source_path: Path to the file to store
            sha256_hash: SHA256 hash of the file (used for filename)
            
        Returns:
            Tuple of (success, message, destination_path)
        """
        source_path = Path(source_path)
        
        # Validate the file
        is_valid, error = self.validate_file(source_path)
        if not is_valid:
            return False, error, None
        
        # Create destination path
        # Store in a directory structure based on the first few chars of the hash
        hash_prefix = sha256_hash[:2]
        dest_dir = self.upload_dir / hash_prefix
        os.makedirs(dest_dir, exist_ok=True)
        
        # Use the hash as the filename but keep the original extension
        extension = source_path.suffix
        dest_path = dest_dir / f"{sha256_hash}{extension}"
        
        try:
            # Copy the file 
            with open(source_path, 'rb') as src_file:
                with open(dest_path, 'wb') as dest_file:
                    dest_file.write(src_file.read())
            
            logger.info(f"Successfully stored file at {dest_path}")
            return True, "File stored successfully", dest_path
        except Exception as e:
            logger.error(f"Error storing file: {str(e)}")
            return False, f"Error storing file: {str(e)}", None
    
    @staticmethod
    def calculate_hashes(file_path: Union[str, Path]) -> Dict[str, str]:
        """
        Calculate multiple hashes for a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary containing md5, sha1, and sha256 hashes
        """
        file_path = Path(file_path)
        
        # Initialize hashers
        md5_hasher = hashlib.md5()
        sha1_hasher = hashlib.sha1()
        sha256_hasher = hashlib.sha256()
        
        # Read file in chunks to handle large files efficiently
        with open(file_path, 'rb') as f:
            # Use 64kb chunks
            for chunk in iter(lambda: f.read(65536), b''):
                md5_hasher.update(chunk)
                sha1_hasher.update(chunk)
                sha256_hasher.update(chunk)
        
        return {
            'md5': md5_hasher.hexdigest(),
            'sha1': sha1_hasher.hexdigest(),
            'sha256': sha256_hasher.hexdigest()
        }

    @staticmethod
    def sanitize_tags(tags_input: Union[str, List[str]]) -> List[str]:
        """
        Sanitize tags from user input.
        
        Args:
            tags_input: String of comma-separated tags or list of tags
            
        Returns:
            List of sanitized tags
        """
        # Convert string input to list
        if isinstance(tags_input, str):
            tags = [tag.strip() for tag in tags_input.split(',')]
        else:
            tags = tags_input
        
        # Sanitize each tag
        sanitized_tags = []
        for tag in tags:
            if not tag:
                continue
                
            # Remove special characters
            tag = re.sub(r'[^\w\.-]', '_', tag)
            
            # Limit length
            tag = tag[:30]
            
            if tag:
                sanitized_tags.append(tag)
        
        # Remove duplicates and sort
        sanitized_tags = sorted(set(sanitized_tags))
        
        return sanitized_tags

# Example usage
if __name__ == "__main__":
    import argparse
    import sys
    
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Sanitize and process malware samples")
    parser.add_argument("file", help="Path to the file to process")
    parser.add_argument("--output-dir", default="/app/data/uploads", help="Directory to store sanitized files")
    parser.add_argument("--max-size", type=int, default=100, help="Maximum file size in MB")
    parser.add_argument("--strict", action="store_true", help="Enable strict mode")
    
    # Parse arguments
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create sanitizer
    sanitizer = MalwareSanitizer(
        upload_dir=args.output_dir,
        max_file_size_mb=args.max_size,
        strict_mode=args.strict
    )
    
    # Process the file
    file_path = Path(args.file)
    
    # Validate the file
    is_valid, error = sanitizer.validate_file(file_path)
    if not is_valid:
        print(f"Error: {error}")
        sys.exit(1)
    
    # Calculate hashes
    print("Calculating hashes...")
    hashes = sanitizer.calculate_hashes(file_path)
    for hash_type, hash_value in hashes.items():
        print(f"{hash_type}: {hash_value}")
    
    # Store the file
    print("Storing file...")
    success, message, dest_path = sanitizer.safe_store_file(file_path, hashes['sha256'])
    if success:
        print(f"File stored successfully at {dest_path}")
    else:
        print(f"Error: {message}")
        sys.exit(1)
    
    print("Processing complete!")
