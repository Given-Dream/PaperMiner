# -*- coding: utf-8 -*-
"""LLM 辅助模块，用于调用 DeepSeek 或自定义 OpenAI 兼容接口。"""

import json
import re
import requests
from pathlib import Path
from typing import Dict, Optional, List

from llm_config import (
    DEEPSEEK_API_BASE,
    DEFAULT_DEEPSEEK_MODEL,
    build_auth_headers,
    endpoint_url,
    load_llm_settings,
)


class LLMHelper:
    """LLM 辅助类，支持 DeepSeek 和自定义 OpenAI 兼容接口。"""

    def __init__(self, model_name: Optional[str] = None,
                 provider: Optional[str] = None,
                 env_path: Optional[Path] = None,
                 require_api: bool = True,
                 debug_dir: Optional[Path] = None):
        """
        初始化 LLM Helper

        Args:
            model_name: 实际模型 ID。兼容旧调用：传入 "deepseek"/"custom"
                且未指定 provider 时，会将其解释为接口类型。
            provider: "deepseek" 或 "custom"；为空时读取 .env。
            env_path: 可选的 .env 路径，主要用于测试。
            require_api: 是否在配置缺失时立即报错。GUI 的正则回退流程会设为
                False，使未配置 API 时仍可完成纯正则章节提取。
            debug_dir: LLM 响应无法解析时的诊断输出目录。为空时兼容旧版，
                使用当前工作目录下的 output/debug。
        """
        settings = load_llm_settings(env_path)
        requested_model = (model_name or "").strip()
        legacy_provider = requested_model.lower()
        if provider is None and legacy_provider in {"deepseek", "custom"}:
            provider = legacy_provider
            requested_model = ""

        self.provider = (provider or settings.provider).strip().lower()
        self.debug_dir = Path(debug_dir) if debug_dir is not None else Path("output") / "debug"
        self.configuration_error = ""
        if self.provider == "deepseek":
            self.api_key = settings.deepseek_api_key
            self.api_base_url = DEEPSEEK_API_BASE
            self.model_name = (
                requested_model or settings.deepseek_model or DEFAULT_DEEPSEEK_MODEL
            )
            if not self.api_key or self.api_key == "sk-your_deepseek_api_key_here":
                self.configuration_error = "未找到有效的 DeepSeek API Key，请在设置中配置"
        elif self.provider == "custom":
            self.api_key = settings.custom_api_key
            self.api_base_url = settings.custom_api_base_url
            self.model_name = requested_model or settings.active_model
            if not self.api_base_url:
                self.configuration_error = "未配置自定义 API 地址，请先在设置中测试并保存"
            elif not self.model_name:
                self.configuration_error = "未选择自定义模型，请先在设置中勾选并保存"
        else:
            raise ValueError(f"不支持的接口类型: {self.provider}")

        self.api_endpoint = ""
        if self.api_base_url:
            try:
                self.api_endpoint = endpoint_url(self.api_base_url, "chat/completions")
            except ValueError as exc:
                self.configuration_error = f"API 地址无效: {exc}"

        if require_api and self.configuration_error:
            raise ValueError(self.configuration_error)
    
    def call_llm(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.1,
                  max_retries: int = 1, verbose: bool = True, json_mode: bool = False) -> Optional[str]:
        """调用 LLM API（带重试机制）

        Args:
            prompt: 提示词
            max_tokens: 最大生成 token 数
            temperature: 温度参数（越低越确定）
            max_retries: 最大重试次数
            verbose: 是否显示详细信息
            json_mode: 是否请求结构化 JSON 输出

        Returns:
            LLM 返回的文本，失败返回 None
        """
        import time

        if self.configuration_error:
            if verbose:
                print(f"    ⚠️  {self.configuration_error}，跳过 LLM 调用")
            return None

        # 显示请求信息
        if verbose:
            prompt_length = len(prompt)
            estimated_tokens = prompt_length // 4  # 粗略估计：4 字符 ≈ 1 token
            print(f"    📊 请求信息:")
            print(f"       - 提示词长度: {prompt_length:,} 字符")
            print(f"       - 估计 Token 数: ~{estimated_tokens:,} tokens")
            print(f"       - 最大返回 Token: {max_tokens:,} tokens")
            print(f"       - 温度参数: {temperature}")
            provider_label = "DeepSeek" if self.provider == "deepseek" else "自定义接口"
            print(f"       - API 接口: {provider_label}")
            print(f"       - 模型: {self.model_name}")

        for attempt in range(max_retries):
            try:
                start_time = time.time()

                if verbose and attempt > 0:
                    print(f"    🔄 第 {attempt + 1} 次尝试...")

                result = self._call_openai_compatible(
                    prompt, max_tokens, temperature, json_mode=json_mode
                )

                elapsed_time = time.time() - start_time

                # 显示响应信息
                if verbose and result:
                    response_length = len(result)
                    estimated_response_tokens = response_length // 4
                    print(f"    ✅ 响应信息:")
                    print(f"       - 响应时间: {elapsed_time:.2f} 秒")
                    print(f"       - 响应长度: {response_length:,} 字符")
                    print(f"       - 估计 Token 数: ~{estimated_response_tokens:,} tokens")

                return result

            except requests.exceptions.Timeout:
                elapsed_time = time.time() - start_time
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5  # 5秒, 10秒, 15秒
                    print(f"    ⚠️  API 调用超时（{elapsed_time:.1f} 秒），{wait_time} 秒后重试（第 {attempt + 1}/{max_retries} 次）...")
                    time.sleep(wait_time)
                else:
                    print(f"    ❌ API 调用超时（{elapsed_time:.1f} 秒），已重试 {max_retries} 次，放弃")
                    return None
            except requests.exceptions.HTTPError as e:
                # 4xx 是语义错误（请求本身问题），重试也救不回来
                elapsed_time = time.time() - start_time
                status = getattr(getattr(e, 'response', None), 'status_code', 0)
                if 400 <= status < 500:
                    print(f"    ❌ LLM 调用被拒绝（{elapsed_time:.1f} 秒, HTTP {status}）: {str(e)}，不重试")
                    return None
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 3
                    print(f"    ⚠️  LLM HTTP 错误（{elapsed_time:.1f} 秒, HTTP {status}）: {str(e)}，{wait_time} 秒后重试（第 {attempt + 1}/{max_retries} 次）...")
                    time.sleep(wait_time)
                else:
                    print(f"    ❌ LLM HTTP 错误（{elapsed_time:.1f} 秒, HTTP {status}）: {str(e)}")
                    return None
            except Exception as e:
                elapsed_time = time.time() - start_time
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 3  # 3秒
                    print(f"    ⚠️  LLM 调用失败（{elapsed_time:.1f} 秒）: {str(e)}，{wait_time} 秒后重试（第 {attempt + 1}/{max_retries} 次）...")
                    time.sleep(wait_time)
                else:
                    print(f"    ❌ LLM 调用失败（{elapsed_time:.1f} 秒）: {str(e)}")
                    return None

        return None

    def _call_openai_compatible(self, prompt: str, max_tokens: int, temperature: float,
                                json_mode: bool = False) -> Optional[str]:
        """调用 OpenAI 兼容接口（流式接收，避免长生成时 read timeout）。"""
        import json as _json

        headers = build_auth_headers(self.api_key)

        data = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            # 开启流式：边生成边下发 chunk，连接保持活跃；用 requests.iter_lines 聚合 SSE
            "stream": True,
        }

        # DeepSeek 支持 stream_options；部分自定义接口会拒绝这个扩展字段。
        if self.provider == "deepseek":
            data["stream_options"] = {"include_usage": True}

        if json_mode:
            data["response_format"] = {"type": "json_object"}

        # (connect_timeout, read_timeout)：连接 10s，单 chunk 间隔最多 90s
        response = requests.post(
            self.api_endpoint, headers=headers, json=data,
            stream=True, timeout=(10, 90),
        )
        response.raise_for_status()

        content_parts = []
        usage = None
        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    if payload == "[DONE]":
                        break
                    continue
                try:
                    chunk = _json.loads(payload)
                except Exception:
                    continue
                choices = chunk.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        content_parts.append(piece)
                chunk_usage = chunk.get("usage")
                if chunk_usage:
                    usage = chunk_usage
        finally:
            response.close()

        if usage:
            print(f"    📈 API 使用统计:")
            if "prompt_tokens" in usage:
                print(f"       - 输入 Token: {usage['prompt_tokens']:,}")
            if "completion_tokens" in usage:
                print(f"       - 输出 Token: {usage['completion_tokens']:,}")
            if "total_tokens" in usage:
                print(f"       - 总计 Token: {usage['total_tokens']:,}")
            if (
                self.provider == "deepseek"
                and "prompt_tokens" in usage
                and "completion_tokens" in usage
            ):
                input_cost = usage["prompt_tokens"] / 1000 * 0.001
                output_cost = usage["completion_tokens"] / 1000 * 0.002
                total_cost = input_cost + output_cost
                print(f"       - 估算成本: ¥{total_cost:.4f} (输入: ¥{input_cost:.4f}, 输出: ¥{output_cost:.4f})")

        return "".join(content_parts) if content_parts else None

    def extract_sections(self, markdown_content: str, prompt_template: str,
                        missing_sections: Optional[List[str]] = None) -> Optional[Dict[str, str]]:
        """使用 LLM 提取论文章节

        Args:
            markdown_content: 完整的 Markdown 文档内容
            prompt_template: 提示词模板
            missing_sections: 需要提取的章节列表（如果为 None，则提取所有章节）

        Returns:
            字典，键为章节名称，值为章节内容
            例如: {"Abstract": "...", "Introduction": "...", ...}
        """
        # 构建完整提示词
        full_prompt = prompt_template.replace("{MARKDOWN_CONTENT}", markdown_content)

        # 如果指定了缺失章节，替换占位符
        if missing_sections and "{TARGET_SECTIONS_LIST}" in full_prompt:
            sections_list = "\n".join([f"- **{section}**" for section in missing_sections])
            full_prompt = full_prompt.replace("{TARGET_SECTIONS_LIST}", sections_list)

        # 调用 LLM（启用 JSON 模式，以提高解析成功率）
        json_mode = True

        # 根据请求的章节数量动态调整 max_tokens；DeepSeek-chat 上限 8192，统一 clamp 到 8000
        # 避免超过上限触发 400 Bad Request。若章节确实很多被截断，下一版再考虑分批调用。
        if missing_sections and len(missing_sections) == 1:
            max_tokens = 8000  # 单个章节给足空间
        else:
            max_tokens = 8000  # 多章节/全部：仍锁在 8000（DeepSeek 硬上限）

        response = self.call_llm(full_prompt, max_tokens=max_tokens, temperature=0.1, json_mode=json_mode)

        if not response:
            return None

        # 解析 LLM 返回的 JSON
        try:
            # 尝试提取 JSON（可能被包裹在 ```json ... ``` 中）
            response = response.strip()

            # 移除可能的 markdown 代码块标记
            if response.startswith("```json"):
                response = response[7:]
            elif response.startswith("```"):
                response = response[3:]

            if response.endswith("```"):
                response = response[:-3]

            response = response.strip()

            # 尝试修复常见的 JSON 错误
            # 1. 修复未转义的反斜杠（LaTeX 公式中常见）
            # 将 \xxx 替换为 \\xxx（但不影响已经转义的 \\xxx）
            import re
            # 使用负向后顾断言，只替换单个反斜杠
            response = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r'\\\\', response)

            # 2. 修复未转义的双引号（在字符串中）
            # 这个比较复杂，暂时跳过，因为可能误伤

            # 解析 JSON
            sections = json.loads(response)

            return sections

        except json.JSONDecodeError as e:
            print(f"    ❌ JSON 解析失败: {str(e)}")
            # 将完整响应保存到调试文件，方便排查问题
            try:
                from pathlib import Path
                self.debug_dir.mkdir(parents=True, exist_ok=True)
                debug_file = self.debug_dir / "llm_section_response.json"
                debug_file.write_text(response, encoding="utf-8")
                print(f"    📝 已保存完整 LLM 响应到: {debug_file}")
            except Exception as save_err:
                print(f"    ⚠️ 无法保存 LLM 响应: {save_err}")
            print(f"    📄 LLM 返回内容（前 500 字符）: {response[:500]}...")

            # 尝试修复截断的 JSON
            if "Unterminated string" in str(e):
                print(f"    🔧 检测到字符串未闭合，尝试修复截断的 JSON...")
                try:
                    # 尝试闭合字符串和 JSON 对象
                    fixed_response = response.rstrip()
                    # 如果最后没有引号，添加引号
                    if not fixed_response.endswith('"'):
                        fixed_response += '"'
                    # 如果最后没有闭合大括号，添加大括号
                    if not fixed_response.endswith('}'):
                        fixed_response += '\n}'

                    sections = json.loads(fixed_response)
                    print(f"    ✅ 修复成功！提取到 {len(sections)} 个章节（内容可能不完整）")
                    print(f"    ⚠️  注意：由于 LLM 输出被截断，章节内容可能不完整")
                    return sections
                except Exception as fix_err:
                    print(f"    ❌ 修复失败: {str(fix_err)}")

            # 尝试宽松 JSON 解析（替换单引号为双引号等常见 LLM 输出问题）
            try:
                print(f"    🔄 尝试使用宽松模式解析...")
                cleaned = response.strip()
                # LLM 有时输出 Python dict 格式（单引号），转为 JSON 双引号
                cleaned = cleaned.replace("'", '"')
                # 移除可能的尾部逗号（JSON 不允许）
                cleaned = re.sub(r',\s*}', '}', cleaned)
                cleaned = re.sub(r',\s*]', ']', cleaned)
                sections = json.loads(cleaned)
                print(f"    ✅ 宽松模式解析成功")
                return sections
            except Exception as e2:
                print(f"    ❌ 宽松模式也失败: {str(e2)}")
                return None


    def classify_section_titles(self, unrecognized_headers: List[tuple]) -> Optional[Dict[str, str]]:
        """使用 LLM 对未识别的章节标题进行分类

        Args:
            unrecognized_headers: 未识别的标题列表，每个元素是 (line_index, header_text, header_level)

        Returns:
            字典，键为标题文本，值为章节类型（Abstract/Introduction/Methods/Results/Discussion/Conclusion）
            如果分类失败返回 None
        """
        if not unrecognized_headers:
            return {}

        # 构建提示词
        headers_text = "\n".join([f"{i+1}. {header}" for i, (_, header, _) in enumerate(unrecognized_headers)])

        prompt = f"""You are an expert in analyzing research paper structures.

I have extracted some section headers from a research paper, but I cannot determine which standard section type they belong to.

Please classify each header into ONE of these standard section types:
- Abstract
- Introduction (background, motivation, related work, literature review, preliminaries, problem statement, objectives, context, scope, theoretical background)
- Methods (methodology, experimental setup, materials, model, modelling, algorithm, classification, formulation, approach, framework, implementation, design, architecture, simulation, numerical methods, data collection, procedures, computational methods, proposed method, system design)
- Results (findings, evaluation, experiments, verification, validation, performance, comparison, analysis, data analysis, experimental results, simulation results, numerical results, observations, benchmarking, case study, application)
- Discussion (analysis, interpretation, implications, comparative analysis)
- Conclusion (summary, future work, concluding remarks, outlook, perspectives, contributions, final remarks)

**Important classification rules**:
1. **Paper title** (usually the first header) → "Unknown"
2. **Article Info**, **Nomenclature**, **Acknowledgements**, **References**, **Appendix**, **Funding**, **Ethics** → "Unknown"
3. **Classification**, **Modelling**, **Model**, **Algorithm**, **Framework**, **Formulation**, **Implementation**, **Design**, **Simulation**, **Proposed Method** → "Methods"
4. **Verification**, **Validation**, **Evaluation**, **Comparison**, **Experiments**, **Performance**, **Benchmark**, **Case Study**, **Application** → "Results"
5. **Analysis**, **Interpretation**, **Implications** → "Discussion" (but "Data Analysis" → "Results")
6. **Summary**, **Future Work**, **Outlook**, **Perspectives**, **Contributions** → "Conclusion"
7. If a header contains numbered sections (e.g., "2. Classification", "3. Modelling"), classify based on the content, not the number
8. If uncertain, use "Unknown"

Headers to classify:
{headers_text}

Return ONLY a JSON object mapping each header number to its section type.

Example output format:
{{
  "1": "Unknown",
  "2": "Methods",
  "3": "Methods",
  "4": "Results"
}}

Your response (JSON only):"""

        print(f"    🤖 使用 LLM 对 {len(unrecognized_headers)} 个未识别标题进行分类...")

        # 调用 LLM（启用 JSON 模式，使用较小的 max_tokens）
        json_mode = (self.model_name == "deepseek")
        response = self.call_llm(prompt, max_tokens=500, temperature=0.1, json_mode=json_mode, verbose=False)

        if not response:
            print(f"    ❌ LLM 分类失败")
            return None

        # 解析 JSON
        try:
            # 清理响应
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

            classification = json.loads(response)

            # 将数字索引映射回标题文本
            result = {}
            for i, (_, header, _) in enumerate(unrecognized_headers):
                key = str(i + 1)
                if key in classification:
                    section_type = classification[key]
                    if section_type != "Unknown":
                        result[header] = section_type
                        print(f"       ✓ {header[:50]}... → {section_type}")

            print(f"    ✅ 成功分类 {len(result)} 个标题")
            return result

        except Exception as e:
            print(f"    ❌ 解析分类结果失败: {str(e)}")
            return None


    def extract_sections_fallback(self, markdown_content: str, return_unrecognized: bool = False):
        """使用正则表达式回退方法提取论文章节（当 LLM 失败时）

        Args:
            markdown_content: 完整的 Markdown 文档内容
            return_unrecognized: 是否返回未识别的章节标题信息

        Returns:
            如果 return_unrecognized=False: 返回字典，键为章节名称，值为章节内容
            如果 return_unrecognized=True: 返回元组 (sections_dict, unrecognized_headers)
                unrecognized_headers 是列表，每个元素是 (line_index, header_text, header_level)
        """
        import re

        print(f"    🔄 使用正则表达式回退方法...")

        lines = markdown_content.split('\n')
        sections = {}
        unrecognized_headers = []  # 存储未识别的章节标题

        # 定义需要排除的章节（论文末尾的致谢、资助、声明、参考文献等）
        exclude_patterns = [
            # 有 # 标记的格式
            r'^#+\s*acknowledgements?\s*$',
            r'^#+\s*\d+[\.．]?\s*acknowledgements?\s*$',
            r'^#+\s*funding\s*$',
            r'^#+\s*\d+[\.．]?\s*funding\s*$',
            r'^#+\s*declarations?\s*$',
            r'^#+\s*\d+[\.．]?\s*declarations?\s*$',
            r'^#+\s*references?\s*$',
            r'^#+\s*\d+[\.．]?\s*references?\s*$',
            r'^#+\s*appendix\s*$',
            r'^#+\s*\d+[\.．]?\s*appendix\s*$',
            r'^#+\s*appendices\s*$',
            r'^#+\s*\d+[\.．]?\s*appendices\s*$',
            r'^#+\s*bibliography\s*$',
            r'^#+\s*\d+[\.．]?\s*bibliography\s*$',
            r'^#+\s*competing\s+interests?\s*$',
            r'^#+\s*\d+[\.．]?\s*competing\s+interests?\s*$',
            r'^#+\s*author\s+contributions?\s*$',
            r'^#+\s*\d+[\.．]?\s*author\s+contributions?\s*$',
            r'^#+\s*data\s+availability\s*$',
            r'^#+\s*\d+[\.．]?\s*data\s+availability\s*$',
            # 新增：更多排除模式
            r'^#+\s*conflict\s+of\s+interests?\s*$',
            r'^#+\s*\d+[\.．]?\s*conflict\s+of\s+interests?\s*$',
            r'^#+\s*ethics\s+(statement|declarations?)\s*$',
            r'^#+\s*\d+[\.．]?\s*ethics\s+(statement|declarations?)\s*$',
            r'^#+\s*consent\s+(for\s+publication|to\s+participate)\s*$',
            r'^#+\s*\d+[\.．]?\s*consent\s+(for\s+publication|to\s+participate)\s*$',
            r'^#+\s*availability\s+of\s+data\s+and\s+materials?\s*$',
            r'^#+\s*\d+[\.．]?\s*availability\s+of\s+data\s+and\s+materials?\s*$',
            r'^#+\s*supplementary\s+(materials?|information)\s*$',
            r'^#+\s*\d+[\.．]?\s*supplementary\s+(materials?|information)\s*$',
            r'^#+\s*abbreviations?\s*$',
            r'^#+\s*\d+[\.．]?\s*abbreviations?\s*$',
            r'^#+\s*nomenclature\s*$',
            r'^#+\s*\d+[\.．]?\s*nomenclature\s*$',
            r'^#+\s*glossary\s*$',
            r'^#+\s*\d+[\.．]?\s*glossary\s*$',
            # 无 # 标记的格式（段落开头）
            r'^acknowledgements?\s',
            r'^funding\s',
            r'^declarations?\s',
            r'^references?\s',
            r'^appendix\s',
            r'^appendices\s',
            r'^bibliography\s',
            r'^competing\s+interests?\s',
            r'^author\s+contributions?\s',
            r'^data\s+availability\s',
            r'^conflict\s+of\s+interests?\s',
            r'^ethics\s+(statement|declarations?)\s',
            r'^supplementary\s+(materials?|information)\s',
            # 中文
            r'^#+\s*致谢\s*$',
            r'^#+\s*\d+[\.．]?\s*致谢\s*$',
            r'^#+\s*参考文献\s*$',
            r'^#+\s*\d+[\.．]?\s*参考文献\s*$',
            r'^#+\s*附录\s*$',
            r'^#+\s*\d+[\.．]?\s*附录\s*$',
            r'^#+\s*资助\s*$',
            r'^#+\s*\d+[\.．]?\s*资助\s*$',
            r'^#+\s*基金\s*$',
            r'^#+\s*\d+[\.．]?\s*基金\s*$',
            r'^#+\s*利益冲突\s*$',
            r'^#+\s*\d+[\.．]?\s*利益冲突\s*$',
            r'^#+\s*作者贡献\s*$',
            r'^#+\s*\d+[\.．]?\s*作者贡献\s*$',
            r'^#+\s*伦理声明\s*$',
            r'^#+\s*\d+[\.．]?\s*伦理声明\s*$',
            r'^#+\s*补充材料\s*$',
            r'^#+\s*\d+[\.．]?\s*补充材料\s*$',
            r'^#+\s*缩略语\s*$',
            r'^#+\s*\d+[\.．]?\s*缩略语\s*$',
        ]

        # 定义章节模式（使用 re.IGNORECASE 标志，所以只需要一种大小写形式）
        section_patterns = {
            'Abstract': [
                r'^#+\s*abstract\s*$',
                r'^abstract\s*:',  # 无 # 标记，Abstract: 后跟内容（带冒号）
                r'^abstract\s+\S+',  # 无 # 标记，Abstract 后直接跟内容（无冒号）
                r'^#+\s*摘要\s*$',
                r'^#+\s*a\s*b\s*s\s*t\s*r\s*a\s*c\s*t\s*$',  # 处理字母间有空格的情况
                r'^#+\s*summary\s*$',  # Summary
                r'^#+\s*executive\s+summary\s*$',  # Executive Summary
            ],
            'Introduction': [
                # 基本格式
                r'^#+\s*introduction\s*$',
                r'^#+\s*\d+[\.．]?\s*introduction\s*$',  # 1. Introduction 或 1．Introduction
                r'^#+\s*[ivx]+[\.．]?\s*introduction\s*$',  # I. Introduction
                # 常见变体
                r'^#+\s*background\s*$',  # Background
                r'^#+\s*\d+[\.．]?\s*background\s*$',  # 1. Background
                r'^#+\s*motivation\s*$',  # Motivation
                r'^#+\s*\d+[\.．]?\s*motivation\s*$',  # 1. Motivation
                r'^#+\s*overview\s*$',  # Overview
                r'^#+\s*\d+[\.．]?\s*overview\s*$',  # 1. Overview
                r'^#+\s*background\s+and\s+motivation\s*$',  # Background and Motivation
                r'^#+\s*\d+[\.．]?\s*background\s+and\s+motivation\s*$',
                r'^#+\s*related\s+works?\s*$',  # Related Work / Related Works
                r'^#+\s*\d+[\.．]?\s*related\s+works?\s*$',  # 2. Related Work
                r'^#+\s*literature\s+review\s*$',  # Literature Review
                r'^#+\s*\d+[\.．]?\s*literature\s+review\s*$',
                r'^#+\s*background\s+and\s+related\s+works?\s*$',  # Background and Related Work
                r'^#+\s*\d+[\.．]?\s*background\s+and\s+related\s+works?\s*$',
                # 新增：更多常见表达
                r'^#+\s*preliminaries\s*$',  # Preliminaries（预备知识）
                r'^#+\s*\d+[\.．]?\s*preliminaries\s*$',
                r'^#+\s*problem\s+(statement|formulation|definition)\s*$',  # Problem Statement
                r'^#+\s*\d+[\.．]?\s*problem\s+(statement|formulation|definition)\s*$',
                r'^#+\s*state\s+of\s+the\s+art\s*$',  # State of the Art
                r'^#+\s*\d+[\.．]?\s*state\s+of\s+the\s+art\s*$',
                r'^#+\s*prior\s+works?\s*$',  # Prior Work
                r'^#+\s*\d+[\.．]?\s*prior\s+works?\s*$',
                r'^#+\s*previous\s+works?\s*$',  # Previous Work
                r'^#+\s*\d+[\.．]?\s*previous\s+works?\s*$',
                r'^#+\s*theoretical\s+background\s*$',  # Theoretical Background
                r'^#+\s*\d+[\.．]?\s*theoretical\s+background\s*$',
                r'^#+\s*context\s*$',  # Context
                r'^#+\s*\d+[\.．]?\s*context\s*$',
                r'^#+\s*scope\s*$',  # Scope
                r'^#+\s*\d+[\.．]?\s*scope\s*$',
                r'^#+\s*objectives?\s*$',  # Objective / Objectives
                r'^#+\s*\d+[\.．]?\s*objectives?\s*$',
                r'^#+\s*aims?\s+and\s+objectives?\s*$',  # Aims and Objectives
                r'^#+\s*\d+[\.．]?\s*aims?\s+and\s+objectives?\s*$',
                # 中文
                r'^#+\s*引言\s*$',
                r'^#+\s*绪论\s*$',
                r'^#+\s*前言\s*$',
                r'^#+\s*背景\s*$',
                r'^#+\s*研究背景\s*$',
                r'^#+\s*相关工作\s*$',
                r'^#+\s*文献综述\s*$',
                r'^#+\s*问题陈述\s*$',
                r'^#+\s*问题定义\s*$',
                r'^#+\s*研究现状\s*$',
                r'^#+\s*理论基础\s*$',
                r'^#+\s*预备知识\s*$',
                r'^#+\s*研究目标\s*$',
            ],
            'Methods': [
                # 基本格式
                r'^#+\s*methods?\s*$',
                r'^#+\s*\d+[\.．]?\s*methods?\s*$',  # 2. Methods
                r'^#+\s*[ivx]+[\.．]?\s*methods?\s*$',  # II. Methods
                r'^#+\s*methodology\s*$',
                r'^#+\s*\d+[\.．]?\s*methodology\s*$',  # 2. Methodology
                # 材料与方法
                r'^#+\s*materials?\s*$',  # Materials（单独出现也算Methods）
                r'^#+\s*\d+[\.．]?\s*materials?\s*$',  # 2. Materials
                r'^#+\s*materials?\s+and\s+methods?\s*$',  # Materials and Methods
                r'^#+\s*\d+[\.．]?\s*materials?\s+and\s+methods?\s*$',  # 2. Materials and Methods
                # 实验相关
                r'^#+\s*experimental?\s*$',  # Experimental
                r'^#+\s*\d+[\.．]?\s*experimental?\s*$',
                r'^#+\s*experimental\s+(methods?|procedures?|section|setup|design)\s*$',  # Experimental Methods/Setup
                r'^#+\s*\d+[\.．]?\s*experimental\s+(methods?|procedures?|section|setup|design)\s*$',
                r'^#+\s*experiments?\s*$',  # Experiments
                r'^#+\s*\d+[\.．]?\s*experiments?\s*$',
                r'^#+\s*procedures?\s*$',  # Procedure / Procedures
                r'^#+\s*\d+[\.．]?\s*procedures?\s*$',
                # 仿真相关
                r'^#+\s*simulation\s*$',  # Simulation
                r'^#+\s*\d+[\.．]?\s*simulation\s*$',
                r'^#+\s*simulation\s+(setup|model|framework|environment)\s*$',  # Simulation Setup
                r'^#+\s*\d+[\.．]?\s*simulation\s+(setup|model|framework|environment)\s*$',
                r'^#+\s*numerical\s+(simulation|methods?|analysis)\s*$',  # Numerical Simulation
                r'^#+\s*\d+[\.．]?\s*numerical\s+(simulation|methods?|analysis)\s*$',
                # 模型相关
                r'^#+\s*models?\s*$',  # Model
                r'^#+\s*\d+[\.．]?\s*models?\s*$',
                r'^#+\s*modeling\s*$',  # Modeling
                r'^#+\s*\d+[\.．]?\s*modeling\s*$',
                r'^#+\s*modelling\s*$',  # Modelling（英式拼写）
                r'^#+\s*\d+[\.．]?\s*modelling\s*$',
                r'^#+\s*model\s+(description|formulation|development|construction)\s*$',  # Model Description
                r'^#+\s*\d+[\.．]?\s*model\s+(description|formulation|development|construction)\s*$',
                r'^#+\s*mathematical\s+(model|formulation|framework)\s*$',  # Mathematical Model
                r'^#+\s*\d+[\.．]?\s*mathematical\s+(model|formulation|framework)\s*$',
                r'^#+\s*theoretical\s+(model|framework|formulation)\s*$',  # Theoretical Model
                r'^#+\s*\d+[\.．]?\s*theoretical\s+(model|framework|formulation)\s*$',
                # 系统设计与实现
                r'^#+\s*implementation\s*$',  # Implementation
                r'^#+\s*\d+[\.．]?\s*implementation\s*$',
                r'^#+\s*system\s+(design|architecture|implementation|description)\s*$',  # System Design
                r'^#+\s*\d+[\.．]?\s*system\s+(design|architecture|implementation|description)\s*$',
                r'^#+\s*design\s*$',  # Design
                r'^#+\s*\d+[\.．]?\s*design\s*$',
                r'^#+\s*architecture\s*$',  # Architecture
                r'^#+\s*\d+[\.．]?\s*architecture\s*$',
                r'^#+\s*framework\s*$',  # Framework
                r'^#+\s*\d+[\.．]?\s*framework\s*$',
                # 算法与方法
                r'^#+\s*algorithms?\s*$',  # Algorithm
                r'^#+\s*\d+[\.．]?\s*algorithms?\s*$',
                r'^#+\s*approach\s*$',  # Approach
                r'^#+\s*\d+[\.．]?\s*approach\s*$',
                r'^#+\s*proposed\s+(method|approach|algorithm|model|system|framework)\s*$',  # Proposed Method
                r'^#+\s*\d+[\.．]?\s*proposed\s+(method|approach|algorithm|model|system|framework)\s*$',
                r'^#+\s*our\s+(method|approach|algorithm|model|system|framework)\s*$',  # Our Method
                r'^#+\s*\d+[\.．]?\s*our\s+(method|approach|algorithm|model|system|framework)\s*$',
                r'^#+\s*the\s+proposed\s+(method|approach|algorithm|model|system)\s*$',  # The Proposed Method
                r'^#+\s*\d+[\.．]?\s*the\s+proposed\s+(method|approach|algorithm|model|system)\s*$',
                # 技术细节
                r'^#+\s*technical\s+(approach|details|description)\s*$',  # Technical Approach
                r'^#+\s*\d+[\.．]?\s*technical\s+(approach|details|description)\s*$',
                # 数据与样本
                r'^#+\s*data\s+(collection|acquisition|preparation|processing)\s*$',  # Data Collection
                r'^#+\s*\d+[\.．]?\s*data\s+(collection|acquisition|preparation|processing)\s*$',
                r'^#+\s*dataset\s*$',  # Dataset
                r'^#+\s*\d+[\.．]?\s*dataset\s*$',
                r'^#+\s*sample\s+(preparation|collection)\s*$',  # Sample Preparation
                r'^#+\s*\d+[\.．]?\s*sample\s+(preparation|collection)\s*$',
                # 分类、分析方法
                r'^#+\s*classification\s*$',  # Classification
                r'^#+\s*\d+[\.．]?\s*classification\s*$',
                r'^#+\s*formulation\s*$',  # Formulation
                r'^#+\s*\d+[\.．]?\s*formulation\s*$',
                r'^#+\s*problem\s+formulation\s*$',  # Problem Formulation
                r'^#+\s*\d+[\.．]?\s*problem\s+formulation\s*$',
                # 计算方法
                r'^#+\s*computational\s+(methods?|approach|framework)\s*$',  # Computational Methods
                r'^#+\s*\d+[\.．]?\s*computational\s+(methods?|approach|framework)\s*$',
                # 中文
                r'^#+\s*方法\s*$',
                r'^#+\s*实验方法\s*$',
                r'^#+\s*研究方法\s*$',
                r'^#+\s*材料与方法\s*$',
                r'^#+\s*实验设计\s*$',
                r'^#+\s*仿真\s*$',
                r'^#+\s*仿真设计\s*$',
                r'^#+\s*数值仿真\s*$',
                r'^#+\s*模型\s*$',
                r'^#+\s*建模\s*$',
                r'^#+\s*数学模型\s*$',
                r'^#+\s*理论模型\s*$',
                r'^#+\s*系统设计\s*$',
                r'^#+\s*算法\s*$',
                r'^#+\s*实现\s*$',
                r'^#+\s*技术方案\s*$',
                r'^#+\s*数据采集\s*$',
                r'^#+\s*数据处理\s*$',
                r'^#+\s*样本制备\s*$',
                r'^#+\s*分类\s*$',
                r'^#+\s*公式推导\s*$',
                r'^#+\s*计算方法\s*$',
            ],
            'Results & Discussion': [
                # 结果与讨论合并
                r'^#+\s*results?\s+and\s+discussions?\s*$',  # Results and Discussion
                r'^#+\s*\d+[\.．]?\s*results?\s+and\s+discussions?\s*$',  # 3. Results and Discussion
                r'^#+\s*[ivx]+[\.．]?\s*results?\s+and\s+discussions?\s*$',
                # 结果
                r'^#+\s*results?\s*$',
                r'^#+\s*\d+[\.．]?\s*results?\s*$',  # 3. Results
                r'^#+\s*[ivx]+[\.．]?\s*results?\s*$',
                r'^#+\s*experimental\s+results?\s*$',  # Experimental Results
                r'^#+\s*\d+[\.．]?\s*experimental\s+results?\s*$',
                r'^#+\s*simulation\s+results?\s*$',  # Simulation Results
                r'^#+\s*\d+[\.．]?\s*simulation\s+results?\s*$',
                r'^#+\s*numerical\s+results?\s*$',  # Numerical Results
                r'^#+\s*\d+[\.．]?\s*numerical\s+results?\s*$',
                r'^#+\s*findings?\s*$',  # Findings
                r'^#+\s*\d+[\.．]?\s*findings?\s*$',
                r'^#+\s*observations?\s*$',  # Observations
                r'^#+\s*\d+[\.．]?\s*observations?\s*$',
                # 讨论
                r'^#+\s*discussions?\s*$',
                r'^#+\s*\d+[\.．]?\s*discussions?\s*$',  # 4. Discussion
                r'^#+\s*[ivx]+[\.．]?\s*discussions?\s*$',
                # 评估与分析
                r'^#+\s*evaluation\s*$',  # Evaluation
                r'^#+\s*\d+[\.．]?\s*evaluation\s*$',
                r'^#+\s*performance\s+(evaluation|analysis|assessment)\s*$',  # Performance Evaluation
                r'^#+\s*\d+[\.．]?\s*performance\s+(evaluation|analysis|assessment)\s*$',
                r'^#+\s*analysis\s*$',  # Analysis
                r'^#+\s*\d+[\.．]?\s*analysis\s*$',
                r'^#+\s*experimental\s+(evaluation|analysis)\s*$',  # Experimental Evaluation
                r'^#+\s*\d+[\.．]?\s*experimental\s+(evaluation|analysis)\s*$',
                r'^#+\s*data\s+analysis\s*$',  # Data Analysis
                r'^#+\s*\d+[\.．]?\s*data\s+analysis\s*$',
                r'^#+\s*statistical\s+analysis\s*$',  # Statistical Analysis
                r'^#+\s*\d+[\.．]?\s*statistical\s+analysis\s*$',
                # 验证相关
                r'^#+\s*verification\s*$',  # Verification
                r'^#+\s*\d+[\.．]?\s*verification\s*$',
                r'^#+\s*validation\s*$',  # Validation
                r'^#+\s*\d+[\.．]?\s*validation\s*$',
                r'^#+\s*model\s+(verification|validation)\s*$',  # Model Verification
                r'^#+\s*\d+[\.．]?\s*model\s+(verification|validation)\s*$',
                r'^#+\s*experimental\s+validation\s*$',  # Experimental Validation
                r'^#+\s*\d+[\.．]?\s*experimental\s+validation\s*$',
                # 案例研究
                r'^#+\s*case\s+stud(y|ies)\s*$',  # Case Study / Case Studies
                r'^#+\s*\d+[\.．]?\s*case\s+stud(y|ies)\s*$',
                r'^#+\s*application\s*$',  # Application
                r'^#+\s*\d+[\.．]?\s*application\s*$',
                r'^#+\s*applications?\s*$',  # Applications
                r'^#+\s*\d+[\.．]?\s*applications?\s*$',
                # 实验
                r'^#+\s*experiments?\s*$',  # Experiments
                r'^#+\s*\d+[\.．]?\s*experiments?\s*$',
                # 比较
                r'^#+\s*comparison\s*$',  # Comparison
                r'^#+\s*\d+[\.．]?\s*comparison\s*$',
                r'^#+\s*comparative\s+(analysis|study|evaluation)\s*$',  # Comparative Analysis
                r'^#+\s*\d+[\.．]?\s*comparative\s+(analysis|study|evaluation)\s*$',
                # 性能相关
                r'^#+\s*performance\s*$',  # Performance
                r'^#+\s*\d+[\.．]?\s*performance\s*$',
                r'^#+\s*benchmark\s*$',  # Benchmark
                r'^#+\s*\d+[\.．]?\s*benchmark\s*$',
                r'^#+\s*benchmarking\s*$',  # Benchmarking
                r'^#+\s*\d+[\.．]?\s*benchmarking\s*$',
                # 中文
                r'^#+\s*结果\s*$',
                r'^#+\s*讨论\s*$',
                r'^#+\s*结果与讨论\s*$',
                r'^#+\s*实验结果\s*$',
                r'^#+\s*仿真结果\s*$',
                r'^#+\s*数值结果\s*$',
                r'^#+\s*分析\s*$',
                r'^#+\s*性能分析\s*$',
                r'^#+\s*数据分析\s*$',
                r'^#+\s*统计分析\s*$',
                r'^#+\s*评估\s*$',
                r'^#+\s*验证\s*$',
                r'^#+\s*模型验证\s*$',
                r'^#+\s*实验验证\s*$',
                r'^#+\s*案例研究\s*$',
                r'^#+\s*应用\s*$',
                r'^#+\s*比较\s*$',
                r'^#+\s*对比分析\s*$',
                r'^#+\s*性能评估\s*$',
                r'^#+\s*基准测试\s*$',
            ],
            'Conclusion': [
                # 基本格式
                r'^#+\s*conclusions?\s*$',  # Conclusion / Conclusions
                r'^#+\s*\d+[\.．]?\s*conclusions?\s*$',  # 4. Conclusions
                r'^#+\s*[ivx]+[\.．]?\s*conclusions?\s*$',  # IV. Conclusions
                # 常见变体
                r'^#+\s*concluding\s+remarks?\s*$',  # Concluding Remarks
                r'^#+\s*\d+[\.．]?\s*concluding\s+remarks?\s*$',
                r'^#+\s*summary\s+and\s+conclusions?\s*$',  # Summary and Conclusions
                r'^#+\s*\d+[\.．]?\s*summary\s+and\s+conclusions?\s*$',
                r'^#+\s*conclusions?\s+and\s+future\s+works?\s*$',  # Conclusions and Future Work
                r'^#+\s*\d+[\.．]?\s*conclusions?\s+and\s+future\s+works?\s*$',
                r'^#+\s*conclusions?\s+and\s+outlook\s*$',  # Conclusions and Outlook
                r'^#+\s*\d+[\.．]?\s*conclusions?\s+and\s+outlook\s*$',
                r'^#+\s*summary\s*$',  # Summary (when used as conclusion)
                r'^#+\s*\d+[\.．]?\s*summary\s*$',
                r'^#+\s*final\s+remarks?\s*$',  # Final Remarks
                r'^#+\s*\d+[\.．]?\s*final\s+remarks?\s*$',
                r'^#+\s*closing\s+remarks?\s*$',  # Closing Remarks
                r'^#+\s*\d+[\.．]?\s*closing\s+remarks?\s*$',
                # 未来工作
                r'^#+\s*future\s+works?\s*$',  # Future Work
                r'^#+\s*\d+[\.．]?\s*future\s+works?\s*$',
                r'^#+\s*future\s+(directions?|research|perspectives?)\s*$',  # Future Directions
                r'^#+\s*\d+[\.．]?\s*future\s+(directions?|research|perspectives?)\s*$',
                r'^#+\s*outlook\s*$',  # Outlook
                r'^#+\s*\d+[\.．]?\s*outlook\s*$',
                r'^#+\s*perspectives?\s*$',  # Perspective / Perspectives
                r'^#+\s*\d+[\.．]?\s*perspectives?\s*$',
                # 总结相关
                r'^#+\s*summary\s+and\s+future\s+works?\s*$',  # Summary and Future Work
                r'^#+\s*\d+[\.．]?\s*summary\s+and\s+future\s+works?\s*$',
                r'^#+\s*summary\s+and\s+outlook\s*$',  # Summary and Outlook
                r'^#+\s*\d+[\.．]?\s*summary\s+and\s+outlook\s*$',
                # 贡献
                r'^#+\s*contributions?\s*$',  # Contribution / Contributions
                r'^#+\s*\d+[\.．]?\s*contributions?\s*$',
                # 影响与意义
                r'^#+\s*implications?\s*$',  # Implications
                r'^#+\s*\d+[\.．]?\s*implications?\s*$',
                # 中文
                r'^#+\s*结论\s*$',
                r'^#+\s*总结\s*$',
                r'^#+\s*结束语\s*$',
                r'^#+\s*展望\s*$',
                r'^#+\s*未来工作\s*$',
                r'^#+\s*总结与展望\s*$',
                r'^#+\s*结论与展望\s*$',
                r'^#+\s*研究展望\s*$',
                r'^#+\s*未来研究方向\s*$',
                r'^#+\s*本文贡献\s*$',
                r'^#+\s*主要贡献\s*$',
            ],
        }

        def get_heading_level(line: str) -> int:
            """
            获取标题的级别
            优先根据编号层级判断（如 1. → 1级, 2.1. → 2级, 3.2.1. → 3级）
            支持全角点号（．）和半角点号（.）
            如果没有编号，则根据 # 的数量判断
            """
            # 尝试匹配编号格式（如 1., 2.1., 3.2.1.，支持全角点）
            # 同时支持半角点 . 和全角点 ．
            # 支持点号后有无空格的情况：# 2.1. Title 或 # 2.1.Title
            # 也支持标题中有其他内容：# (xxx) 2.1. Title
            numbering_match = re.search(r'(\d+(?:[\.．]\d+)*)[\.．](?:\s|[A-Za-z])', line)
            if numbering_match:
                # 计算编号的层级（点的数量 + 1）
                numbering = numbering_match.group(1)
                # 统一替换全角点为半角点再计数
                numbering_normalized = numbering.replace('．', '.')
                level = numbering_normalized.count('.') + 1
                return level
            else:
                # 根据 # 的数量判断
                header_match = re.match(r'^(#+)\s', line)
                if header_match:
                    return len(header_match.group(1))
                return 0

        def get_section_name_for_header(line: str, section_patterns_dict: dict) -> str:
            """
            判断一行标题属于哪个主要章节
            返回章节名称，如果不属于任何主要章节则返回空字符串
            """
            line_stripped = line.strip()
            for sec_name, patterns in section_patterns_dict.items():
                if any(re.match(pattern, line_stripped, re.IGNORECASE) for pattern in patterns):
                    return sec_name
            return ""

        def is_exclude_section(line: str, exclude_patterns_list: list) -> bool:
            """
            判断一行是否是需要排除的章节（如 Acknowledgements, References 等）
            返回 True 表示是排除章节，False 表示不是
            """
            line_stripped = line.strip()
            return any(re.match(pattern, line_stripped, re.IGNORECASE) for pattern in exclude_patterns_list)

        # 查找每个章节
        for section_name, patterns in section_patterns.items():
            section_start = -1
            section_end = -1
            section_level = 0  # 章节标题的级别

            # 查找章节开始
            for i, line in enumerate(lines):
                line_stripped = line.strip()
                if any(re.match(pattern, line_stripped, re.IGNORECASE) for pattern in patterns):
                    section_start = i
                    # 计算标题级别
                    section_level = get_heading_level(line_stripped)
                    # 特殊处理：如果是无 # 标记的章节（如 Abstract），设为 1 级标题
                    if section_level == 0:
                        section_level = 1
                    print(f"    ✓ 找到 {section_name}: {line_stripped}")
                    break

            if section_start == -1:
                print(f"    ⚠️  未找到 {section_name}")
                continue

            # 查找章节结束（下一个不同的主要章节的标题或排除章节）
            for i in range(section_start + 1, len(lines)):
                line_stripped = lines[i].strip()
                
                # 优先检查是否是排除章节（无论是否有 # 标记）
                if is_exclude_section(line_stripped, exclude_patterns):
                    # 遇到排除章节，立即结束当前章节
                    section_end = i
                    print(f"    ⓘ 在排除章节处停止: {line_stripped[:50]}...")
                    break
                
                # 检查是否是标题（有 # 标记）
                if re.match(r'^#+\s', line_stripped):
                    # 获取当前标题的级别
                    current_level = get_heading_level(line_stripped)
                    # 如果是同级或更高级的标题
                    if current_level > 0 and current_level <= section_level:
                        # 检查是否是另一个不同的主要章节的标题
                        matched_section = get_section_name_for_header(line_stripped, section_patterns)
                        if matched_section and matched_section != section_name:
                            # 是另一个主要章节的标题，结束当前章节
                            section_end = i
                            break
                        # 如果是同级标题但不匹配主要章节模式：
                        # 只有当它是数字编号的章节（如 # 3.）时才结束当前章节
                        # （避免像 # (1) KSlF 这样的子标题导致提前结束）
                        if current_level == section_level and not matched_section:
                            # 检查是否是数字编号的章节标题（如 # 3. 或 # 3 ）
                            is_numbered_heading = bool(re.match(r'^#+\s*\d+[\.．]?\s', line_stripped))
                            if is_numbered_heading:
                                # 同级数字编号标题，结束当前章节
                                section_end = i
                                print(f"    ⓘ 遇到同级标题，结束当前章节: {line_stripped[:50]}...")
                                break
                            # 否则，这是当前章节的子标题（如 # (1) xxx），继续
                        # 如果是当前章节的子标题或匹配当前章节模式，继续

            if section_end == -1:
                section_end = len(lines)

            # 提取章节内容
            section_content = '\n'.join(lines[section_start:section_end])
            sections[section_name] = section_content

        # 特殊处理：如果找到了 Results 和 Discussion，合并它们
        if 'Results' in sections and 'Discussion' in sections:
            sections['Results & Discussion'] = sections['Results'] + '\n\n' + sections['Discussion']
            del sections['Results']
            del sections['Discussion']
            print(f"    ✓ 合并 Results 和 Discussion")

        # 如果需要返回未识别的标题，收集它们
        if return_unrecognized:
            # 遍历所有一级标题，找出未被识别的
            for i, line in enumerate(lines):
                line_stripped = line.strip()
                # 检查是否是标题
                if re.match(r'^#+\s', line_stripped):
                    level = get_heading_level(line_stripped)
                    # 只关注一级标题（主要章节）
                    if level == 1:
                        # 检查是否已被识别
                        matched_section = get_section_name_for_header(line_stripped, section_patterns)
                        # 检查是否是排除章节
                        is_excluded = is_exclude_section(line_stripped, exclude_patterns)
                        # 如果既不是已识别章节，也不是排除章节，则记录为未识别
                        if not matched_section and not is_excluded:
                            unrecognized_headers.append((i, line_stripped, level))

            if unrecognized_headers:
                print(f"    ⓘ 发现 {len(unrecognized_headers)} 个未识别的一级标题")
                for _, header, _ in unrecognized_headers:
                    print(f"       - {header[:60]}...")

        if sections:
            print(f"    ✅ 正则表达式方法成功提取 {len(sections)} 个章节")
        else:
            print(f"    ❌ 正则表达式方法未能提取任何章节")

        if return_unrecognized:
            return sections, unrecognized_headers
        else:
            return sections


def load_prompt_template(prompt_file: Path) -> str:
    """
    加载提示词模板

    Args:
        prompt_file: 提示词文件路径

    Returns:
        提示词模板字符串
    """
    if not prompt_file.exists():
        raise FileNotFoundError(f"提示词文件不存在: {prompt_file}")

    with open(prompt_file, 'r', encoding='utf-8') as f:
        return f.read()


def fix_relative_paths(content: str) -> str:
    """
    修复章节内容中的相对路径
    将 Figure/ 改为 ../Figure/
    将 Tables/ 改为 ../Tables/

    Args:
        content: 章节内容

    Returns:
        修复后的内容
    """
    import re

    # 修复图片路径：![](Figure/xxx) → ![](../Figure/xxx)
    content = re.sub(r'!\[\]\(Figure/', r'![](../Figure/', content)

    # 修复表格路径（如果有的话）：![](Tables/xxx) → ![](../Tables/xxx)
    content = re.sub(r'!\[\]\(Tables/', r'![](../Tables/', content)

    return content


def save_sections(sections: Dict[str, str], output_dir: Path) -> List[str]:
    """
    保存提取的章节到文件

    Args:
        sections: 章节字典
        output_dir: 输出目录

    Returns:
        保存的文件路径列表
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []

    # 章节名称映射（用于文件命名）
    section_name_map = {
        "abstract": "Abstract.md",
        "introduction": "Introduction.md",
        "methods": "Methods.md",
        "methodology": "Methods.md",
        "experimental": "Methods.md",
        "materials and methods": "Methods.md",
        "results": "Results & Discussion.md",
        "discussion": "Results & Discussion.md",
        "results and discussion": "Results & Discussion.md",
        "results & discussion": "Results & Discussion.md",
        "conclusion": "Conclusion.md",
        "conclusions": "Conclusion.md",
        "concluding remarks": "Conclusion.md",
        "summary and conclusions": "Conclusion.md",
    }

    # 用于合并 Results 和 Discussion
    results_content = []

    for section_key, content in sections.items():
        if not content or not content.strip():
            continue

        # 修复相对路径（图片、表格）
        content = fix_relative_paths(content)

        # 标准化章节名称
        section_key_lower = section_key.lower().strip()

        # 处理 Results 和 Discussion 的合并
        if any(key in section_key_lower for key in ["result", "discussion"]):
            # 内容已经包含标题，直接添加（带上章节编号用于排序）
            import re
            # 提取第一个标题的编号
            match = re.search(r'^# (\d+)\.', content, re.MULTILINE)
            section_number = int(match.group(1)) if match else 999
            results_content.append((section_number, content))
            continue

        # 获取文件名
        filename = section_name_map.get(section_key_lower, f"{section_key}.md")
        output_file = output_dir / filename

        # 保存文件（内容已经包含标题，直接写入）
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(content)

        saved_files.append(str(output_file))

    # 保存合并的 Results & Discussion
    if results_content:
        # 按章节编号排序
        results_content.sort(key=lambda x: x[0])
        # 只保留内容部分
        sorted_content = [content for _, content in results_content]

        output_file = output_dir / "Results & Discussion.md"
        with open(output_file, 'w', encoding='utf-8') as f:
            # 使用分隔符连接多个部分
            f.write("\n\n---\n\n".join(sorted_content))
        saved_files.append(str(output_file))

    return saved_files
