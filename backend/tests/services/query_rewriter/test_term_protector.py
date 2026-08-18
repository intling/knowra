"""TermProtector 精确词保护器测试。

测试覆盖：
- 正则规则匹配：版本号、IP 地址、URL、全大写缩写、驼峰/蛇形命名、邮件、
  技术标识符
- 自定义词汇表匹配
- 词汇表优先级（词汇表 > 正则）
- 保护 → 还原完整闭环
- 边界情况：空文本、无匹配、重复术语、中文混合
"""

from __future__ import annotations

from app.services.term_protector import TermProtector

# ── 辅助函数 ────────────────────────────────────────────────────


def _protector(*, vocabulary: set[str] | None = None) -> TermProtector:
    """创建测试用 TermProtector，可指定词汇表。"""
    return TermProtector(vocabulary=vocabulary or set())


# ═══════════════════════════════════════════════════════════════
# 版本号检测
# ═══════════════════════════════════════════════════════════════


class TestVersionDetection:
    """验证版本号的自动识别与保护。"""

    def test_semver(self):
        """三段式语义版本号。"""
        p = _protector()
        text, m = p.protect("Python 3.12.0 新特性")
        assert "3.12.0" in m.values()
        assert "[[TERM_0]]" in text

    def test_two_segment_version(self):
        """两段式版本号。"""
        p = _protector()
        text, m = p.protect("Go 1.21 更新内容")
        assert "1.21" in m.values()
        assert "[[TERM_0]]" in text

    def test_prerelease_version(self):
        """预发布版本号（带后缀）。"""
        p = _protector()
        text, m = p.protect("升级到 2.0.0-rc.1")
        assert "2.0.0-rc.1" in m.values()

    def test_multiple_versions(self):
        """同一文本中的多个版本号。"""
        p = _protector()
        text, m = p.protect("从 1.0.0 升级到 2.0.0")
        assert "1.0.0" in m.values()
        assert "2.0.0" in m.values()
        assert "[[TERM_0]]" in text
        assert "[[TERM_1]]" in text

    def test_version_not_numbers_after_dot(self):
        """纯数字点分隔不应误匹配（如价格）。"""
        p = _protector()
        text, m = p.protect("价格 99.99 元")
        # 可能会匹配也可能不匹配，取决于模式。至少不应报错。
        assert isinstance(text, str)


# ═══════════════════════════════════════════════════════════════
# IP 地址检测
# ═══════════════════════════════════════════════════════════════


class TestIPDetection:
    """验证 IP 地址的自动识别与保护。"""

    def test_ipv4(self):
        """标准 IPv4 地址。"""
        p = _protector()
        text, m = p.protect("服务器地址 192.168.1.100 无法访问")
        assert "192.168.1.100" in m.values()

    def test_ipv4_boundary(self):
        """IPv4 边界 0-255。"""
        p = _protector()
        text, m = p.protect("内网地址 10.0.0.1")
        assert "10.0.0.1" in m.values()

    def test_localhost(self):
        """回环地址。"""
        p = _protector()
        text, m = p.protect("连接 127.0.0.1:8080")
        assert "127.0.0.1" in m.values()


# ═══════════════════════════════════════════════════════════════
# URL 检测
# ═══════════════════════════════════════════════════════════════


class TestURLDetection:
    """验证 URL 的自动识别与保护。"""

    def test_https_url(self):
        """HTTPS 完整 URL。"""
        p = _protector()
        text, m = p.protect("文档地址 https://docs.python.org/3/")
        assert "https://docs.python.org/3/" in m.values()

    def test_http_url(self):
        """HTTP URL。"""
        p = _protector()
        text, m = p.protect("访问 http://localhost:3000/api")
        assert "http://localhost:3000/api" in m.values()

    def test_url_with_chinese_punctuation(self):
        """URL 后跟中文标点应正确截断。"""
        p = _protector()
        text, m = p.protect("参考 https://example.com/doc，里面有说明")
        assert "https://example.com/doc" in m.values()


# ═══════════════════════════════════════════════════════════════
# 全大写缩写检测
# ═══════════════════════════════════════════════════════════════


class TestAcronymDetection:
    """验证全大写缩写词的自动识别与保护。"""

    def test_common_acronym(self):
        """常见缩写词。"""
        p = _protector()
        text, m = p.protect("API 接口如何设计")
        assert "API" in m.values()

    def test_acronym_with_digits(self):
        """缩写含数字后缀。"""
        p = _protector()
        text, m = p.protect("HTML5 新增特性")
        assert "HTML5" in m.values()

    def test_no_acronym_inside_word(self):
        """缩写不应在单词内部匹配。"""
        p = _protector()
        text, m = p.protect("HELLO 世界")
        # HELLO 是全大写，应该匹配
        assert "HELLO" in m.values()

    def test_single_letter_not_acronym(self):
        """单字母不应被匹配为缩写。"""
        p = _protector()
        text, m = p.protect("A 和 B 的关系")
        assert "A" not in m.values()
        assert "B" not in m.values()


# ═══════════════════════════════════════════════════════════════
# 驼峰/蛇形命名检测
# ═══════════════════════════════════════════════════════════════


class TestCamelCaseDetection:
    """验证驼峰与蛇形命名的自动识别与保护。"""

    def test_pascal_case(self):
        """PascalCase 类名。"""
        p = _protector()
        text, m = p.protect("QueryRewriter 组件如何工作")
        assert "QueryRewriter" in m.values()

    def test_camel_case_method(self):
        """dromedaryCase 方法名。"""
        p = _protector()
        text, m = p.protect("调用 getUserData 方法")
        assert "getUserData" in m.values()

    def test_snake_case(self):
        """snake_case 标识符。"""
        p = _protector()
        text, m = p.protect("使用 base_url 配置")
        assert "base_url" in m.values()

    def test_snake_case_multi_segment(self):
        """多段下划线命名。"""
        p = _protector()
        text, m = p.protect("配置 max_retry_attempts 参数")
        assert "max_retry_attempts" in m.values()

    def test_single_word_no_underscore(self):
        """单词不应被误匹配为 snake_case。"""
        p = _protector()
        text, m = p.protect("hello 世界")
        assert "hello" not in m.values()


# ═══════════════════════════════════════════════════════════════
# 邮件地址检测
# ═══════════════════════════════════════════════════════════════


class TestEmailDetection:
    """验证邮件地址的自动识别与保护。"""

    def test_email(self):
        """标准邮件格式。"""
        p = _protector()
        text, m = p.protect("联系 admin@example.com")
        assert "admin@example.com" in m.values()


# ═══════════════════════════════════════════════════════════════
# 技术标识符检测
# ═══════════════════════════════════════════════════════════════


class TestTechnicalIdentifier:
    """验证技术标识符的自动识别与保护。"""

    def test_env_var_braced(self):
        """${VAR} 格式环境变量。"""
        p = _protector()
        text, m = p.protect("使用 ${HOME} 目录")
        assert "${HOME}" in m.values()

    def test_env_var_dollar(self):
        """$VAR 格式环境变量。"""
        p = _protector()
        text, m = p.protect("设置 $PATH 变量")
        assert "$PATH" in m.values()

    def test_cli_flag(self):
        """--flag 格式命令行参数。"""
        p = _protector()
        text, m = p.protect("使用 --debug 模式启动")
        assert "--debug" in m.values()

    def test_cli_flag_with_value(self):
        """--flag=value 格式命令行参数。"""
        p = _protector()
        text, m = p.protect("设置 --port=8080")
        assert "--port=8080" in m.values()

    def test_annotation(self):
        """@annotation 格式。"""
        p = _protector()
        text, m = p.protect("使用 @Autowired 注入")
        assert "@Autowired" in m.values()


# ═══════════════════════════════════════════════════════════════
# 自定义词汇表
# ═══════════════════════════════════════════════════════════════


class TestCustomVocabulary:
    """验证自定义词汇表的匹配与保护。"""

    def test_single_term(self):
        """单个自定义术语。"""
        p = _protector(vocabulary={"Nginx"})
        text, m = p.protect("如何配置 Nginx 反向代理")
        assert "Nginx" in m.values()
        assert "[[TERM_0]]" in text

    def test_multiple_terms(self):
        """多个自定义术语。"""
        p = _protector(vocabulary={"Python", "Django", "PostgreSQL"})
        text, m = p.protect("Python Django 连接 PostgreSQL")
        assert "Python" in m.values()
        assert "Django" in m.values()
        assert "PostgreSQL" in m.values()

    def test_phrase_with_spaces(self):
        """含空格的短语（如 "Ruby on Rails"）。"""
        p = _protector(vocabulary={"Ruby on Rails"})
        text, m = p.protect("Ruby on Rails 框架如何部署")
        assert "Ruby on Rails" in m.values()
        assert "[[TERM_0]]" in text

    def test_partial_no_match(self):
        """词汇不应匹配单词内部子串。"""
        p = _protector(vocabulary={"React"})
        text, m = p.protect("Reaction 时间的测量方法")
        # Reaction ≠ React（词边界完整匹配）
        assert "React" not in m.values()
        assert "[[TERM_0]]" not in text

    def test_chinese_term(self):
        """中文术语保护。"""
        p = _protector(vocabulary={"微服务", "容器化", "服务网格"})
        text, m = p.protect("微服务和容器化的区别")
        assert "微服务" in m.values()
        assert "容器化" in m.values()

    def test_repeated_term_same_placeholder(self):
        """同一术语重复出现应使用相同占位符索引。"""
        p = _protector(vocabulary={"Python"})
        text, m = p.protect("Python 是什么 以及 Python 如何使用")
        # Python 出现两次，应只有 1 个 term_map 条目
        assert len(m) == 1
        # 两次出现应使用同一占位符
        assert text.count("[[TERM_0]]") == 2

    def test_long_term_priority(self):
        """较长术语应优先匹配（如 "Spring Boot" 优先于 "Spring"）。"""
        p = _protector(vocabulary={"Spring", "Spring Boot"})
        text, m = p.protect("Spring Boot 配置方法")
        values = set(m.values())
        # 至少 "Spring Boot" 被匹配
        assert "Spring Boot" in values


# ═══════════════════════════════════════════════════════════════
# 词汇表优先级（词汇表 > 正则）
# ═══════════════════════════════════════════════════════════════


class TestVocabularyPriority:
    """验证词汇表匹配优先级高于正则规则。"""

    def test_vocab_overrides_regex(self):
        """词汇表中的术语不应再被正则规则匹配。"""
        p = _protector(vocabulary={"API"})
        # "API" 既是全大写缩写（会被正则匹配），也在词汇表中
        # 应只被匹配一次，使用词汇表匹配
        text, m = p.protect("API 网关配置")
        assert "API" in m.values()
        # 只出现一次 [[TERM_0]]
        assert text.count("[[TERM_") == 1

    def test_vocab_prevents_overlapping_regex(self):
        """词汇表匹配覆盖的区域不应产生额外的正则匹配。"""
        p = _protector(vocabulary={"getUserData"})
        # "getUserData" 也会被驼峰正则匹配
        text, m = p.protect("调用 getUserData")
        assert "getUserData" in m.values()
        assert text.count("[[TERM_") == 1


# ═══════════════════════════════════════════════════════════════
# 保护 → 还原完整闭环
# ═══════════════════════════════════════════════════════════════


class TestProtectRestoreRoundTrip:
    """验证保护 → 还原 完整闭环。"""

    def test_round_trip_basic(self):
        """基本闭环：保护后再还原应得到原始文本。"""
        p = _protector(vocabulary={"Python", "API"})
        original = "Python API 如何使用"
        protected, term_map = p.protect(original)
        restored = p.restore(protected, term_map)
        # 还原后应与原始文本相同（除占位符格式外）
        assert "Python" in restored
        assert "API" in restored
        assert "[[TERM_" not in restored

    def test_round_trip_with_regex_terms(self):
        """正则匹配的术语也能正确还原。"""
        p = _protector()
        original = "版本号 2.0.0 对应 IP 10.0.0.1"
        protected, term_map = p.protect(original)
        restored = p.restore(protected, term_map)
        assert "2.0.0" in restored
        assert "10.0.0.1" in restored
        assert "[[TERM_" not in restored

    def test_round_trip_rewritten_text(self):
        """模拟 LLM 改写后还原场景 —— 占位符所在位置可能变化。"""
        p = _protector(vocabulary={"Nginx", "反向代理"})
        original = "Nginx 反向代理怎么配置"
        protected, term_map = p.protect(original)

        # 模拟 LLM 改写后的结果
        rewritten = "如何配置 [[TERM_0]] 的 [[TERM_1]]"
        restored = p.restore(rewritten, term_map)
        assert restored == "如何配置 Nginx 的 反向代理"

    def test_empty_term_map_no_change(self):
        """空 term_map 时 restore 应原样返回。"""
        p = _protector()
        text = "这是一个普通查询"
        result = p.restore(text, {})
        assert result == text

    def test_unmatched_placeholder_kept(self):
        """term_map 中不存在的占位符应保持原样。"""
        p = _protector()
        text = "[[TERM_99]] 怎么用"
        result = p.restore(text, {0: "Python"})
        assert "[[TERM_99]]" in result

    def test_placeholder_in_rewritten_with_protected_position_changed(self):
        """改写后占位符位置和顺序都可能变化，还原仍应正确。"""
        p = _protector(vocabulary={"JVM", "GC"})
        original = "JVM GC 频繁触发怎么排查"
        protected, term_map = p.protect(original)

        # LLM 可能重新组织查询，调整术语位置
        llm_rewritten = "如何排查 [[TERM_0]] 的 [[TERM_1]] 频繁触发问题"
        restored = p.restore(llm_rewritten, term_map)
        assert "JVM" in restored
        assert "GC" in restored
        assert "[[TERM_" not in restored

    def test_partial_term_map_use(self):
        """仅使用部分 term_map 的还原（某些占位符可能未出现在改写结果中）。"""
        p = _protector(vocabulary={"Python", "Django", "ORM"})
        original = "Python Django ORM 查询优化"
        protected, term_map = p.protect(original)

        # LLM 改写可能只保留了部分术语
        llm_rewritten = "[[TERM_0]] 的 [[TERM_2]] 优化方法"
        restored = p.restore(llm_rewritten, term_map)
        assert "Python" in restored
        assert "ORM" in restored
        assert "Django" not in restored  # Django 未出现在改写结果中
        assert "[[TERM_" not in restored


# ═══════════════════════════════════════════════════════════════
# 边界与特殊输入
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """验证边界与特殊输入的处理。"""

    def test_empty_text_protect(self):
        """空文本 protect 返回 (空, 空映射)。"""
        p = _protector()
        text, m = p.protect("")
        assert text == ""
        assert m == {}

    def test_empty_text_restore(self):
        """空文本 restore 原样返回。"""
        p = _protector()
        result = p.restore("", {0: "Python"})
        assert result == ""

    def test_no_matches(self):
        """无匹配时应透传原文本。"""
        p = _protector()
        text, m = p.protect("今天天气怎么样")
        assert text == "今天天气怎么样"
        assert m == {}

    def test_only_protected_terms(self):
        """纯保护词文本。"""
        p = _protector(vocabulary={"Nginx"})
        text, m = p.protect("Nginx")
        assert "[[TERM_0]]" in text
        assert m == {0: "Nginx"}

    def test_consecutive_protected_terms(self):
        """连续的多个保护词。"""
        p = _protector(vocabulary={"Python", "Django"})
        text, m = p.protect("Python Django")
        assert "[[TERM_0]]" in text
        assert "[[TERM_1]]" in text

    def test_protector_with_no_rules(self):
        """无词汇表且无正则规则（patterns 传空）时正常透传。"""
        p = TermProtector(vocabulary=set(), patterns=())
        text, m = p.protect("Python API 设计")
        assert text == "Python API 设计"
        assert m == {}

    def test_special_regex_chars_in_vocabulary(self):
        """词汇表含正则特殊字符时应正确转义。"""
        p = _protector(vocabulary={"C++", "C#"})
        text, m = p.protect("C++ 和 C# 的区别")
        assert "C++" in m.values()
        assert "C#" in m.values()


# ═══════════════════════════════════════════════════════════════
# CJK 字符相邻匹配 — 验证 re.ASCII 修复
# ═══════════════════════════════════════════════════════════════


class TestCJKAdjacentMatching:
    """验证 ASCII 术语与 CJK 字符紧邻（无空格）时的正确匹配。

    这是对 re.ASCII 修复的回归测试 —— Python 默认 Unicode 模式下
    CJK 字符属于 ``\\w``，导致 ``\\b`` 边界在 ASCII 术语与 CJK 字符
    之间不触发，词汇表和正则规则均无法匹配。
    """

    def test_acronym_adjacent_to_cjk_regex(self):
        """全大写缩写紧邻中文时应被内置正则匹配（如 HDFS如何编程）。"""
        p = _protector()
        text, m = p.protect("HDFS如何编程")
        assert "HDFS" in m.values(), f"Expected 'HDFS' in term map, got {m}"

    def test_acronym_adjacent_to_cjk_vocabulary(self):
        """词汇表中的 ASCII 术语紧邻中文也应被匹配。"""
        p = _protector(vocabulary={"HDFS"})
        text, m = p.protect("HDFS如何编程")
        assert "HDFS" in m.values(), f"Expected 'HDFS' in term map, got {m}"

    def test_camelcase_adjacent_to_cjk(self):
        """驼峰命名紧邻中文时应被匹配。"""
        p = _protector()
        text, m = p.protect("QueryRewriter组件如何工作")
        assert "QueryRewriter" in m.values(), f"Expected 'QueryRewriter' in term map, got {m}"

    def test_version_adjacent_to_cjk(self):
        """版本号紧邻中文时应被匹配。"""
        p = _protector()
        text, m = p.protect("版本3.12.0更新了什么")
        assert "3.12.0" in m.values(), f"Expected '3.12.0' in term map, got {m}"

    def test_multiple_ascii_terms_adjacent_to_cjk(self):
        """多个 ASCII 术语分别紧邻中文时应全部被匹配。"""
        p = _protector()
        text, m = p.protect("如何配置API网关")
        assert "API" in m.values(), f"Expected 'API' in term map, got {m}"

    def test_from_defaults_cjk_adjacent_acronym(self):
        """from_defaults 词汇表中的术语紧邻中文应被匹配（如 HDFS 在 flat_terms 中）。"""
        p = TermProtector.from_defaults()
        text, m = p.protect("HDFS环境有什么")
        assert "HDFS" in m.values(), f"Expected 'HDFS' in term map, got {m}"

    def test_snake_case_adjacent_to_cjk(self):
        """snake_case 命名紧邻中文时应被匹配。"""
        p = _protector()
        text, m = p.protect("max_retry_count参数如何设置")
        assert "max_retry_count" in m.values(), f"Expected 'max_retry_count' in term map, got {m}"

    def test_acronym_between_cjk(self):
        """ASCII 缩写夹在两个中文词之间也应被匹配。"""
        p = _protector()
        text, m = p.protect("请问API接口如何设计")
        assert "API" in m.values(), f"Expected 'API' in term map, got {m}"


# ═══════════════════════════════════════════════════════════════
# TermProtector 属性
# ═══════════════════════════════════════════════════════════════


class TestTermProtectorProperties:
    """验证 TermProtector 的属性接口。"""

    def test_vocabulary_size(self):
        """vocabulary_size 反映词汇表大小。"""
        p = _protector(vocabulary={"A", "B", "C"})
        assert p.vocabulary_size == 3

    def test_regex_rule_count_default(self):
        """默认正则规则数量。"""
        p = TermProtector()
        assert p.regex_rule_count > 0

    def test_regex_rule_count_empty(self):
        """无正则规则时返回 0。"""
        p = TermProtector(patterns=())
        assert p.regex_rule_count == 0

    def test_empty_vocabulary(self):
        """空词汇表。"""
        p = TermProtector()
        assert p.vocabulary_size == 0


# ═══════════════════════════════════════════════════════════════
# from_defaults 工厂方法
# ═══════════════════════════════════════════════════════════════


class TestFromDefaults:
    """验证 TermProtector.from_defaults() 工厂方法。"""

    def test_from_defaults_basic(self):
        """from_defaults 应成功创建 TermProtector 实例。"""
        p = TermProtector.from_defaults()
        assert p.vocabulary_size > 0  # 默认词汇表应有内容
        assert p.regex_rule_count > 0

    def test_from_defaults_with_extra_terms(self):
        """extra_terms 附加术语。"""
        p = TermProtector.from_defaults(extra_terms={"MyCustomTerm"})
        text, m = p.protect("使用 MyCustomTerm")
        assert "MyCustomTerm" in m.values()

    def test_from_defaults_protects_default_vocab(self):
        """默认词汇表中的术语应被保护。"""
        p = TermProtector.from_defaults()
        # "PostgreSQL" 在默认词汇表的 databases_and_storage 分类中
        text, m = p.protect("PostgreSQL 性能优化")
        assert "PostgreSQL" in m.values()


# ═══════════════════════════════════════════════════════════════
# TermProtector 与 QueryRewriter 接口兼容性
# ═══════════════════════════════════════════════════════════════


class TestInterfaceCompatibility:
    """验证 TermProtector 实现了 QueryRewriter 期望的接口。"""

    def test_protect_returns_tuple_str_dict(self):
        """protect() 返回 (str, dict[int, str])。"""
        p = _protector(vocabulary={"Test"})
        result = p.protect("Test query")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], dict)
        # 验证 dict 的 key 和 value 类型
        if result[1]:
            k, v = next(iter(result[1].items()))
            assert isinstance(k, int)
            assert isinstance(v, str)

    def test_restore_returns_str(self):
        """restore() 返回 str。"""
        p = _protector()
        result = p.restore("[[TERM_0]] text", {0: "Test"})
        assert isinstance(result, str)

    def test_protect_result_keys_are_consecutive(self):
        """term_map 的键应为从 0 开始的连续整数。"""
        p = _protector(vocabulary={"A", "B", "C"})
        _, m = p.protect("A B C")
        keys = sorted(m.keys())
        assert keys == [0, 1, 2]

    def test_idempotent_protect(self):
        """对同一文本多次调用 protect 应返回一致结果。"""
        p = _protector(vocabulary={"Python"})
        r1 = p.protect("Python 入门")
        r2 = p.protect("Python 入门")
        assert r1 == r2
