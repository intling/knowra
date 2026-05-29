## MODIFIED Requirements

### Requirement: 上传配置
系统 SHALL 通过配置管理上传存储目录、单文件大小限制和允许内容类型，避免在业务代码中硬编码环境差异，并确保文档处理首批支持的文件类型可以进入上传存储流程。

#### Scenario: 配置上传存储目录
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取上传存储目录
- **AND** 上传服务 MUST 使用该目录保存原始文件

#### Scenario: 配置单文件大小限制
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取单文件大小限制
- **AND** 上传服务 MUST 使用该限制拒绝超限文件

#### Scenario: 配置允许内容类型
- **WHEN** 后端应用启动
- **THEN** 系统 MUST 从配置中读取允许上传的内容类型
- **AND** 上传服务 MUST 使用该配置决定是否接受受限类型文件
- **AND** 默认或示例配置 MUST 覆盖 TXT、Markdown、PDF、DOCX、PPT/PPTX 对应的内容类型
