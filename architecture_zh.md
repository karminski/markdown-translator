# Markdown 翻译架构

## 概述

Markdown 翻译器是一个**模块化、异步优先的管道架构**，用于使用 OpenRouter API 将 Markdown 文件翻译成中文。该系统遵循清晰的职责分离，并采用基于接口的设计模式，强调安全性、性能和可维护性。

## 核心架构组件

### 管道架构

```
输入文件 → 分割器 → 翻译器 → 验证器 → 合并器 → 输出文件
```

### 组件分解

#### A. 编排层
- **`TranslationEngine`** (`engine.py`)：中央编排器，管理整个工作流程
- **`TranslationPool`** (`translator.py`)：带有信号量控制的并发翻译处理
- **工厂模式**：`create_translation_engine()` 用于依赖注入

#### B. 处理组件
- **`MarkdownSplitter`** (`splitter.py`)：智能分割，保留 Markdown 语法（代码块、表格、列表）
- **`IntegrityValidator`** (`validator.py`)：基于标记的内容验证
- **`ContentMerger`** (`merger.py`)：带有错误处理的翻译片段重组

#### C. 基础设施组件
- **`SecurityManager`** (`security.py`)：全面的安全验证（文件路径、内容、API 响应）
- **`ConfigManager`** (`config.py`)：基于环境的配置和 API 客户端创建
- **`PerformanceMonitor`** (`performance.py`)：实时性能跟踪和优化
- **`RichProgressReporter`** (`progress.py`)：用户友好的进度报告

#### D. 接口层 (`interfaces.py`)
定义清晰契约的抽象基类：
- `ISplitter`, `ITranslator`, `IValidator`, `IMerger`, `IConfigManager`
- 便于测试和组件替换

#### E. 数据模型 (`models.py`)
基于 Pydantic 的模型：
- `FileChunk`, `TranslationResult`, `TranslationProgress`
- `TranslationStats`, `MergeResult`, `ValidationResult`

## 关键设计模式

### 1. 基于接口的设计
所有核心组件都实现了接口，使得：
- 测试时易于模拟
- 组件替换
- 清晰的 API 边界

### 2. 异步优先架构
- 基于 Python 的 `asyncio`，带有信号量控制的并发处理
- 通过 `aiofiles` 实现非阻塞文件操作
- 带有重试逻辑的高效 API 请求处理

### 3. 模块化管道
每个阶段都有单一职责：
1. **分割**：保留 Markdown 结构
2. **翻译**：带有验证的并发 API 调用
3. **验证**：确保内容完整性
4. **合并**：带有统计信息的重组

### 4. 全面的错误处理
- 指数退避重试策略（`RetryStrategy` 类）
- 翻译失败时的优雅降级
- 可恢复操作的检查点系统

### 5. 安全优先的方法
- **输入验证**：文件路径、扩展名、大小限制
- **内容安全**：检测恶意模式
- **API 安全**：响应验证和清理
- **临时文件管理**：安全清理

## 工作流执行

### CLI 入口点 (`cli.py`)
```bash
markdown-translator -i README.md -o README_zh.md
mt -i docs.md --chunk-size 1000 --concurrency 10
```

### 翻译过程流
1. **安全验证**：输入/输出路径安全检查
2. **配置**：加载 API 凭证和设置
3. **性能优化**：自动调整分块大小/并发度
4. **文件分割**：保留语法的智能分块
5. **并发翻译**：带有速率限制的并行 API 调用
6. **内容验证**：基于标记的完整性验证
7. **结果合并**：带有错误报告的重组
8. **统计生成**：性能和成功指标

## 依赖项与配置

### 核心依赖项
- **API 客户端**：`openai>=1.0.0`（OpenRouter 兼容）
- **异步框架**：`aiohttp>=3.8.0`, `asyncio-throttle>=1.0.0`
- **CLI & UI**：`click>=8.0.0`, `rich>=12.0.0`
- **数据验证**：`pydantic>=2.0.0`
- **文件操作**：`aiofiles>=23.0.0`, `psutil>=5.9.0`

### 配置 (`config.py`)
所需的环境变量：
```bash
TRANSLATE_API_TOKEN=sk-or-v1-...  # OpenRouter API 密钥
TRANSLATE_API=https://openrouter.ai/api/v1  # 可选
TRANSLATE_MODEL=qwen/qwen-2.5-72b-instruct  # 可选
```

## 性能特性

1. **自动优化**：`PerformanceOptimizer` 建议最佳分块大小/并发度
2. **监控**：跟踪 API 响应时间、内存使用和吞吐量
3. **并发控制**：基于信号量的限制防止 API 节流
4. **资源管理**：在高资源使用时暂停处理

## 安全特性

1. **路径安全**：验证文件扩展名，防止遍历攻击
2. **内容验证**：检测输入/输出中的恶意模式
3. **API 安全**：验证和清理 API 响应
4. **敏感数据**：从日志中删除令牌/密钥
5. **文件大小限制**：防止处理过大的文件

## 关键文件位置

- **入口点**：`markdown_translator/cli.py:402` (`cli_entry_point`)
- **编排**：`markdown_translator/engine.py:35` (`TranslationEngine`)
- **翻译**：`markdown_translator/translator.py:62` (`TranslationPool`)
- **配置**：`markdown_translator/config.py:14` (`ConfigManager`)
- **安全**：`markdown_translator/security.py:31` (`SecurityManager`)

## 架构优势

1. **模块化**：通过接口实现职责分离
2. **可扩展性**：易于添加新的翻译提供者或验证规则
3. **弹性**：全面的错误处理和重试逻辑
4. **安全性**：管道中的多层安全验证
5. **用户体验**：丰富的进度报告和有用的错误消息
6. **性能**：带有自动优化的异步架构

## 详细组件交互

### TranslationEngine 工作流
```python
# 简化的工作流来自 engine.py
async def translate_file():
    # 1. 安全验证
    input_validation = security_manager.validate_file_path(input_path)
    output_validation = security_manager.validate_output_path(output_path)

    # 2. 性能优化
    optimal_chunk_size = performance_optimizer.suggest_optimal_chunk_size()
    optimal_concurrency = performance_optimizer.suggest_optimal_concurrency()

    # 3. 文件分割
    chunks = await splitter.split_file(input_path)

    # 4. 并发翻译
    translation_results = await translator.translate_chunks(chunks)

    # 5. 结果合并
    merge_result = await merger.merge_translations(translation_results, output_path)

    # 6. 统计生成
    stats = merger.generate_statistics(translation_results)
    return stats
```

### 安全验证层
1. **文件路径验证**：检查扩展名、权限、遍历尝试
2. **内容验证**：翻译前扫描恶意模式
3. **API 响应验证**：验证和清理 API 响应
4. **输出验证**：确保安全的输出文件创建

### 性能监控指标
- API 响应时间和成功率
- 内存使用和系统资源利用率
- 吞吐量（每秒处理的分块数）
- 并发级别和信号量利用率

## 扩展点

架构支持多个扩展点：

1. **新的翻译提供者**：实现 `ITranslator` 接口
2. **自定义验证器**：实现 `IValidator` 接口
3. **替代分割器**：实现 `ISplitter` 接口
4. **额外的安全检查**：扩展 `SecurityManager` 类
5. **自定义进度报告**：实现 `IProgressReporter` 接口

此架构展示了一个精心设计的翻译系统，平衡了性能、安全性和可维护性，同时为最终用户提供了一个强大的 CLI 接口。