# 文档解析服务：调用 MinerU 等解析服务把 PDF/图片转为 Markdown
import io
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# MinerU 自部署 FastAPI 的 file_parse 接口默认单文件上限（字节）
MAX_FILE_SIZE = 200 * 1024 * 1024


class DocParseError(Exception):
    """文档解析失败"""


async def parse_document_with_model(
    file_content: bytes,
    filename: str,
    endpoint: str,
    provider: str = "mineru",
    api_key: Optional[str] = None,
    params: Optional[dict] = None,
) -> str:
    """用模型配置中的文档解析服务解析文件，返回 Markdown 文本

    Args:
        file_content: 文件字节内容
        filename: 文件名（用于判断类型）
        endpoint: 解析服务地址
        provider: mineru(MinerU自部署) / mineru_api(MinerU官方) / custom
        api_key: 官方API需要的token
        params: 解析参数 output_format/language/backend_url/parse_method

    Returns:
        解析出的 Markdown 文本
    """
    params = params or {}

    if not endpoint:
        raise DocParseError("未配置解析服务地址")

    if len(file_content) > MAX_FILE_SIZE:
        raise DocParseError(f"文件过大: {len(file_content)} 字节，上限 200MB")

    if provider == "mineru_api":
        return await _parse_mineru_official(file_content, filename, api_key, params)
    else:
        # mineru / mineru_self / custom 均走自部署 /file_parse
        return await _parse_mineru_self(file_content, filename, endpoint, params)


async def _parse_mineru_self(
    file_content: bytes,
    filename: str,
    endpoint: str,
    params: dict,
) -> str:
    """MinerU 自部署版：POST /file_parse (multipart)"""
    url = f"{endpoint.rstrip('/')}/file_parse"
    output_format = params.get("output_format", "markdown")

    data = {
        "output_format": output_format,
        "parse_method": params.get("parse_method", "auto"),
        "backend_url": params.get("backend_url", "pipeline"),
        "return_content": "true",
        "is_json_md_dump": "false",
    }
    lang = params.get("language")
    if lang:
        data["lang_list"] = f'["{lang}"]'

    files = {"files": (filename, io.BytesIO(file_content))}

    try:
        async with httpx.AsyncClient(timeout=600, follow_redirects=True) as client:
            resp = await client.post(url, data=data, files=files)
    except httpx.ConnectError as e:
        raise DocParseError(f"无法连接解析服务 {url}: {e}")
    except httpx.TimeoutException:
        raise DocParseError(f"解析超时（大文件可能需要数分钟）: {url}")

    if resp.status_code != 200:
        raise DocParseError(f"解析服务返回 {resp.status_code}: {resp.text[:300]}")

    result = resp.json()
    back_msg = result.get("back_msg")
    if back_msg:
        raise DocParseError(f"解析失败: {back_msg}")

    md_content = result.get("md_content")
    if not md_content:
        raise DocParseError("解析服务未返回内容")
    return md_content


async def _parse_mineru_official(
    file_content: bytes,
    filename: str,
    api_key: Optional[str],
    params: dict,
) -> str:
    """MinerU 官方API：申请上传链接 -> 上传 -> 轮询结果

    文档: https://mineru.net/apiManage/docs
    """
    if not api_key:
        raise DocParseError("MinerU官方API需要配置API Key（mineru.net 申请）")

    headers = {"Authorization": f"Bearer {api_key}"}
    is_ocr = bool(params.get("enable_ocr", True))

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        # 1. 申请上传链接（单文件）
        resp = await client.post(
            "https://mineru.net/api/v4/file-urls/batch",
            headers=headers,
            json={
                "enable_formula": True,
                "enable_table": True,
                "language": params.get("language", "ch"),
                "files": [{"name": filename, "is_ocr": is_ocr, "data_id": filename}],
            },
        )
        if resp.status_code != 200:
            raise DocParseError(f"申请上传链接失败 {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        if body.get("code") != 0:
            raise DocParseError(f"申请上传链接失败: {body.get('msg')}")
        batch = body["data"]
        batch_id = batch["batch_id"]
        upload_url = batch["file_urls"][0]

        # 2. 上传文件
        put_resp = await client.put(
            upload_url,
            content=file_content,
            headers={"Content-Type": "application/octet-stream"},
        )
        if put_resp.status_code not in (200, 201):
            raise DocParseError(f"文件上传失败 {put_resp.status_code}")

        # 3. 轮询解析结果（最多10分钟）
        import asyncio
        for _ in range(60):
            await asyncio.sleep(10)
            poll = await client.get(
                f"https://mineru.net/api/v4/extract-results/batch/{batch_id}",
                headers=headers,
            )
            if poll.status_code != 200:
                continue
            poll_body = poll.json()
            if poll_body.get("code") != 0:
                raise DocParseError(f"查询结果失败: {poll_body.get('msg')}")
            items = poll_body.get("data", {}).get("extract_result", [])
            if not items:
                continue
            item = items[0]
            state = item.get("state")
            if state == "done":
                full = item.get("full_zip_url")
                if not full:
                    raise DocParseError("解析完成但未返回结果文件")
                return await _download_mineru_zip_md(client, full)
            if state == "failed":
                raise DocParseError(f"解析失败: {item.get('err_msg', '未知错误')}")

        raise DocParseError("解析超时（超过10分钟）")


async def _download_mineru_zip_md(client: httpx.AsyncClient, zip_url: str) -> str:
    """下载 MinerU 官方API的结果zip，取其中的 .md 文件"""
    import zipfile

    resp = await client.get(zip_url)
    if resp.status_code != 200:
        raise DocParseError(f"下载解析结果失败 {resp.status_code}")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        md_names = [n for n in zf.namelist() if n.endswith(".md")]
        if not md_names:
            raise DocParseError("解析结果中未找到 Markdown 文件")
        return zf.read(md_names[0]).decode("utf-8", errors="ignore")
