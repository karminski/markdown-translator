# Markdown Translator Architecture

## Overview

The Markdown Translator is a **modular, async-first pipeline architecture** for translating Markdown files to Chinese using the OpenRouter API. The system follows a clear separation of concerns with interface-based design patterns, emphasizing security, performance, and maintainability.

## Core Architecture Components

### Pipeline Architecture

```
Input File → Splitter → Translator → Validator → Merger → Output File
```

### Component Breakdown

#### A. Orchestration Layer
- **`TranslationEngine`** (`engine.py`): Central orchestrator managing the entire workflow
- **`TranslationPool`** (`translator.py`): Concurrent translation processing with semaphore control
- **Factory Pattern**: `create_translation_engine()` for dependency injection

#### B. Processing Components
- **`MarkdownSplitter`** (`splitter.py`): Intelligent splitting preserving Markdown syntax (code blocks, tables, lists)
- **`IntegrityValidator`** (`validator.py`): Content validation with marker-based integrity checking
- **`ContentMerger`** (`merger.py`): Reassembles translated chunks with error handling

#### C. Infrastructure Components
- **`SecurityManager`** (`security.py`): Comprehensive security validation (file paths, content, API responses)
- **`ConfigManager`** (`config.py`): Environment-based configuration with API client creation
- **`PerformanceMonitor`** (`performance.py`): Real-time performance tracking and optimization
- **`RichProgressReporter`** (`progress.py`): User-friendly progress reporting

#### D. Interface Layer (`interfaces.py`)
Abstract base classes defining clear contracts:
- `ISplitter`, `ITranslator`, `IValidator`, `IMerger`, `IConfigManager`
- Enables easy testing and component swapping

#### E. Data Models (`models.py`)
Pydantic-based models:
- `FileChunk`, `TranslationResult`, `TranslationProgress`
- `TranslationStats`, `MergeResult`, `ValidationResult`

## Key Design Patterns

### 1. Interface-Based Design
All core components implement interfaces, enabling:
- Easy mocking for testing
- Component replacement
- Clear API boundaries

### 2. Async-First Architecture
- Built on Python's `asyncio` with semaphore-based concurrency control
- Non-blocking file operations via `aiofiles`
- Efficient API request handling with retry logic

### 3. Modular Pipeline
Each stage has single responsibility:
1. **Splitting**: Preserves Markdown structure
2. **Translation**: Concurrent API calls with validation
3. **Validation**: Ensures content integrity
4. **Merging**: Reassembles with statistics

### 4. Comprehensive Error Handling
- Exponential backoff retry strategy (`RetryStrategy` class)
- Graceful degradation for failed translations
- Checkpoint system for resumable operations

### 5. Security-First Approach
- **Input Validation**: File paths, extensions, size limits
- **Content Security**: Suspicious pattern detection
- **API Security**: Response validation and sanitization
- **Temporary File Management**: Secure cleanup

## Workflow Execution

### CLI Entry Points (`cli.py`)
```bash
markdown-translator -i README.md -o README_zh.md
mt -i docs.md --chunk-size 1000 --concurrency 10
```

### Translation Process Flow
1. **Security Validation**: Input/output path security checks
2. **Configuration**: Load API credentials and settings
3. **Performance Optimization**: Auto-tuning of chunk size/concurrency
4. **File Splitting**: Intelligent chunking preserving syntax
5. **Concurrent Translation**: Parallel API calls with rate limiting
6. **Content Validation**: Marker-based integrity verification
7. **Result Merging**: Reassembly with error reporting
8. **Statistics Generation**: Performance and success metrics

## Dependencies & Configuration

### Core Dependencies
- **API Client**: `openai>=1.0.0` (OpenRouter compatibility)
- **Async Framework**: `aiohttp>=3.8.0`, `asyncio-throttle>=1.0.0`
- **CLI & UI**: `click>=8.0.0`, `rich>=12.0.0`
- **Data Validation**: `pydantic>=2.0.0`
- **File Operations**: `aiofiles>=23.0.0`, `psutil>=5.9.0`

### Configuration (`config.py`)
Environment variables required:
```bash
TRANSLATE_API_TOKEN=sk-or-v1-...  # OpenRouter API key
TRANSLATE_API=https://openrouter.ai/api/v1  # Optional
TRANSLATE_MODEL=qwen/qwen-2.5-72b-instruct  # Optional
```

## Performance Features

1. **Auto-Optimization**: `PerformanceOptimizer` suggests optimal chunk size/concurrency
2. **Monitoring**: Tracks API response times, memory usage, throughput
3. **Concurrency Control**: Semaphore-based limiting prevents API throttling
4. **Resource Management**: Pauses processing during high resource usage

## Security Features

1. **Path Security**: Validates file extensions, prevents traversal attacks
2. **Content Validation**: Detects malicious patterns in input/output
3. **API Security**: Validates and sanitizes API responses
4. **Sensitive Data**: Redacts tokens/secrets from logs
5. **File Size Limits**: Prevents processing excessively large files

## Key File Locations

- **Entry Points**: `markdown_translator/cli.py:402` (`cli_entry_point`)
- **Orchestration**: `markdown_translator/engine.py:35` (`TranslationEngine`)
- **Translation**: `markdown_translator/translator.py:62` (`TranslationPool`)
- **Configuration**: `markdown_translator/config.py:14` (`ConfigManager`)
- **Security**: `markdown_translator/security.py:31` (`SecurityManager`)

## Architecture Strengths

1. **Modularity**: Clear separation of concerns via interfaces
2. **Extensibility**: Easy to add new translation providers or validation rules
3. **Resilience**: Comprehensive error handling and retry logic
4. **Security**: Multi-layer security validation throughout pipeline
5. **User Experience**: Rich progress reporting and helpful error messages
6. **Performance**: Async architecture with auto-optimization

## Detailed Component Interactions

### TranslationEngine Workflow
```python
# Simplified workflow from engine.py
async def translate_file():
    # 1. Security validation
    input_validation = security_manager.validate_file_path(input_path)
    output_validation = security_manager.validate_output_path(output_path)

    # 2. Performance optimization
    optimal_chunk_size = performance_optimizer.suggest_optimal_chunk_size()
    optimal_concurrency = performance_optimizer.suggest_optimal_concurrency()

    # 3. File splitting
    chunks = await splitter.split_file(input_path)

    # 4. Concurrent translation
    translation_results = await translator.translate_chunks(chunks)

    # 5. Result merging
    merge_result = await merger.merge_translations(translation_results, output_path)

    # 6. Statistics generation
    stats = merger.generate_statistics(translation_results)
    return stats
```

### Security Validation Layers
1. **File Path Validation**: Checks extensions, permissions, traversal attempts
2. **Content Validation**: Scans for malicious patterns before translation
3. **API Response Validation**: Validates and sanitizes API responses
4. **Output Validation**: Ensures safe output file creation

### Performance Monitoring Metrics
- API response times and success rates
- Memory usage and system resource utilization
- Throughput (chunks processed per second)
- Concurrency levels and semaphore utilization

## Extension Points

The architecture supports several extension points:

1. **New Translation Providers**: Implement `ITranslator` interface
2. **Custom Validators**: Implement `IValidator` interface
3. **Alternative Splitters**: Implement `ISplitter` interface
4. **Additional Security Checks**: Extend `SecurityManager` class
5. **Custom Progress Reporting**: Implement `IProgressReporter` interface

This architecture demonstrates a well-engineered translation system that balances performance, security, and maintainability while providing a robust CLI interface for end users.