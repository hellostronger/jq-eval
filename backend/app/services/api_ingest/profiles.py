# 大厂 / 通用 HTTP 接入预设
#
# 这里只放「有公开文档、能确定请求形状」的配置。AK/SK 签名类接口
# （阿里百炼知识库、腾讯 ADP/LKE、华为 AppStage）无法用通用 Bearer 调通，
# 暂不提供假预设；它们可以：
#   1) 私有化/控制台完成知识库建设，用 jq-eval 只做问答评测；
#   2) 在自有网关后转成统一 API，再用通用 profile 接入。
#
# 参考文档集中记录（代码注释要求）：
# - 百度千帆 AppBuilder: https://cloud.baidu.com/doc/qianfan-api/s/tm7wzq8ek
# - 百度千帆检索:       https://cloud.baidu.com/doc/qianfan-api/s/5mgq9zd5a
# - 阿里百炼应用:       https://help.aliyun.com/zh/model-studio/rag-knowledge-base-api-guide
# - 腾讯元器:           https://yuanqi.tencent.com/guide/publish-agent-api-documentation
# - 腾讯 LKE 对话:      https://cloud.tencent.com/document/product/1759/105561
# - 火山方舟:           https://www.volcengine.com/docs/82379
# - 火山 Viking 知识库: https://www.volcengine.com/docs/vector_database_vikingdb/add
# - 讯飞星火:           https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html
# - 华为 AppStage:      https://support.huaweicloud.com/api-appstage/CreateKnowledgeBase.html
# - 京东言犀:           https://docs.jdcloud.com/cn/agents/api-overview
from typing import Any, Dict


def _openai_ask(path: str = "/chat/completions") -> Dict[str, Any]:
    """OpenAI 兼容对话模板：大多数大厂都提供该形态"""
    return {
        "method": "POST",
        "path": path,
        "body": {
            "model": "{{model}}",
            "messages": [{"role": "user", "content": "{{question}}"}],
            "stream": False,
        },
        "answer_path": "choices.0.message.content",
        "contexts_path": "choices.0.message.contexts",
        "retrieval_ids_path": "choices.0.message.retrieval_ids",
    }


PROFILES: Dict[str, Dict[str, Any]] = {
    # ------------------------------------------------------------ 百度
    "baidu_qianfan": {
        "display_name": "百度千帆 AppBuilder",
        "api_endpoint": "https://qianfan.baidubce.com",
        "api_doc_url": "https://cloud.baidu.com/doc/qianfan-api/s/tm7wzq8ek",
        "verified": False,
        "notes": (
            "对话走 /v2/chat/completions（OpenAI 兼容）。知识库的 "
            "?Action=CreateKnowledgeBase/GetDocumentList 需按账号实际版本核对 Action 名；"
            "应用与知识库绑定需在千帆控制台完成。可用 ingest_profile 覆盖。"
        ),
        "profile": {
            "ask": _openai_ask("/v2/chat/completions"),
            "list_kb": {
                "method": "POST",
                "path": "/v2/knowledgeBase",
                "params": {"Action": "ListKnowledgeBases"},
                "body": {},
                "items_path": "result.knowledgeBases",
                "id_path": "id",
                "name_path": "name",
            },
            "create_kb": {
                "method": "POST",
                "path": "/v2/knowledgeBase",
                "params": {"Action": "CreateKnowledgeBase"},
                "body": {"name": "{{name}}"},
                "id_path": "result.id",
                "name_path": "result.name",
            },
        },
    },
    # ------------------------------------------------------------ 阿里
    "aliyun_bailian": {
        "display_name": "阿里云百炼",
        "api_endpoint": "https://dashscope.aliyuncs.com",
        "api_doc_url": "https://help.aliyun.com/zh/model-studio/rag-knowledge-base-api-guide",
        "verified": False,
        "notes": (
            "应用调用使用 DashScope Bearer（sk-）；知识库维护接口为 RAM AK/SK 签名，"
            "通用连接器不代签。请在百炼控制台建库，或经自建网关转成 Bearer 后配置 "
            "ingest_profile。需要 app_id / pipeline_ids。"
        ),
        "profile": {
            "ask": {
                "method": "POST",
                "path": "/api/v1/apps/{{app_id}}/completion",
                "body": {
                    "input": {"prompt": "{{question}}"},
                    "parameters": {
                        "rag_options": {"pipeline_ids": "{{pipeline_ids}}"}
                    },
                },
                # 百炼应用返回 output.text；引用在 output.doc_references 的结构体里，
                # 通用路径无法抽取纯文本，故不声明 contexts_path（检索指标需另配）。
                "answer_path": "output.text",
            },
        },
    },
    # ------------------------------------------------------------ 腾讯
    "tencent_hunyuan": {
        "display_name": "腾讯混元",
        "api_endpoint": "https://api.hunyuan.cloud.tencent.com/v1",
        "api_doc_url": "https://cloud.tencent.com/document/product/1729",
        "verified": False,
        "notes": "OpenAI 兼容对话；知识库能力走腾讯云 LKE/ADP（TC3 签名，通用连接器不代签）。",
        "profile": {"ask": _openai_ask()},
    },
    "tencent_yuanqi": {
        "display_name": "腾讯元器",
        "api_endpoint": "https://yuanqi.tencent.com",
        "api_doc_url": "https://yuanqi.tencent.com/guide/publish-agent-api-documentation",
        "verified": False,
        "notes": "仅开放智能体对话；知识库与智能体创建需在元器控制台完成。需 app_id。",
        "profile": {
            "ask": {
                "method": "POST",
                "path": "/openapi/v1/agent/chat/completions",
                "body": {
                    "assistant_id": "{{app_id}}",
                    "messages": [{"role": "user", "content": "{{question}}"}],
                    "stream": False,
                },
                # 元器把召回信息放在 steps 中，不同版本字段有差异；默认只取回答
                "answer_path": "data.messages.-1.content",
            },
        },
    },
    # ------------------------------------------------------------ 字节
    "volcengine_ark": {
        "display_name": "火山引擎方舟",
        "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
        "api_doc_url": "https://www.volcengine.com/docs/82379",
        "verified": False,
        "notes": (
            "对话可用 OpenAI 兼容 /chat/completions；带知识库的 Bot 用 "
            "/bots/chat/completions（model 填 Bot ID）。知识库本体是 Viking，"
            "其建库/上传接口部分仍需 AK/SK 签名，需经控制台或自建网关。"
        ),
        "profile": {"ask": _openai_ask()},
    },
    # ------------------------------------------------------------ 讯飞
    "xfyun_spark": {
        "display_name": "讯飞星火",
        "api_endpoint": "https://spark-api-open.xf-yun.com/v1",
        "api_doc_url": "https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html",
        "verified": False,
        "notes": "OpenAI 兼容对话；星火知识库（/v1/knowledge/create、/v1/files）需按文档补充 profile。",
        "profile": {"ask": _openai_ask()},
    },
    # ------------------------------------------------------------ 通用
    "openai_compatible": {
        "display_name": "OpenAI 兼容 RAG",
        "api_endpoint": "",
        "api_doc_url": "",
        "verified": False,
        "notes": "任意 OpenAI 兼容网关；知识库步骤请配置 ingest_profile 或手动完成。",
        "profile": {"ask": _openai_ask()},
    },
}
