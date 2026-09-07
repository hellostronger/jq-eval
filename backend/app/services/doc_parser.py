# 文档解析服务：调用 MinerU 等解析服务把 PDF/图片转为 Markdown
import io
import asyncio
import logging
from typing import Optional, List, Dict, Any, Callable, Awaitable

import httpx

logger = logging.getLogger(__name__)

# MinerU 自部署 FastAPI 的 file_parse 接口默认单文件上限（字节）
MAX_FILE_SIZE = 200 * 1024 * 1024


class DocParseError(Exception):
    """文档解析失败"""


class MineruBatchClient:
    """MinerU 官方API 批量客户端

    文档: https://mineru.net/apiManage/docs
    流程: POST /api/v4/file-urls/batch 申请预签名链接
        -> PUT 逐个上传文件（不带 Authorization）
        -> GET /api/v4/extract-results/batch/{batch_id} 轮询
        -> 下载 full_zip_url 解出 md/content_list.json
    """

    BASE_URL = "https://mineru.net/api/v4"

    def __init__(self, api_key: str):
        if not api_key:
            raise DocParseError("MinerU官方API需要配置API Key（mineru.net 申请）")
        self.headers = {"Authorization": f"Bearer {api_key}"}

    async def submit(
        self,
        client: httpx.AsyncClient,
        files: List[Dict[str, Any]],
        params: dict,
    ) -> str:
        """申请上传链接并提交文件

        Args:
            files: [{"name": 文件名, "content": 字节}]（顺序与返回的 file_urls 一一对应）
            params: language / enable_ocr 等解析参数
        Returns:
            batch_id
        """
        body = {
            "enable_formula": True,
            "enable_table": True,
            "language": params.get("language", "ch"),
            "files": [
                {"name": f["name"], "is_ocr": bool(params.get("enable_ocr", True)), "data_id": f["name"]}
                for f in files
            ],
        }
        resp = await client.post(f"{self.BASE_URL}/file-urls/batch", headers=self.headers, json=body)
        if resp.status_code != 200:
            raise DocParseError(f"申请上传链接失败 {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        if data.get("code") != 0:
            raise DocParseError(f"申请上传链接失败: {data.get('msg')}")
        batch_id = data["data"]["batch_id"]
        upload_urls = data["data"]["file_urls"]

        # 逐个上传（PUT 不带 Authorization，否则签名校验失败）
        for f, url in zip(files, upload_urls):
            put = await client.put(
                url,
                content=f["content"],
                headers={"Content-Type": "application/octet-stream"},
            )
            if put.status_code not in (200, 201):
                raise DocParseError(f"文件 {f['name']} 上传失败 {put.status_code}")
        return batch_id

    async def poll(
        self,
        client: httpx.AsyncClient,
        batch_id: str,
        interval: float = 10.0,
        timeout: float = 3600.0,
        on_progress: Optional[Callable[[List[Dict[str, Any]]], Awaitable[None]]] = None,
    ) -> List[Dict[str, Any]]:
        """轮询批量解析结果直到所有文件到终态

        Returns:
            extract_result 列表，每项含 file_name/state/err_msg/full_zip_url
        """
        elapsed = 0.0
        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
            try:
                resp = await client.get(
                    f"{self.BASE_URL}/extract-results/batch/{batch_id}",
                    headers=self.headers,
                )
            except httpx.HTTPError as e:
                logger.warning(f"轮询解析结果网络异常: {e}")
                continue
            if resp.status_code != 200:
                logger.warning(f"轮询解析结果返回 {resp.status_code}")
                continue
            body = resp.json()
            if body.get("code") != 0:
                raise DocParseError(f"查询解析结果失败: {body.get('msg')}")
            items = body.get("data", {}).get("extract_result", [])
            if on_progress:
                await on_progress(items)
            if items and all(it.get("state") in ("done", "failed") for it in items):
                return items
        raise DocParseError(f"解析超时（超过 {int(timeout / 60)} 分钟）")

    async def fetch_result_zip(self, client: httpx.AsyncClient, zip_url: str) -> Dict[str, Any]:
        """下载结果 zip，解出 md 内容与 content_list

        Returns:
            {"md_content": str, "content_list": list|None}
        """
        import zipfile

        resp = await client.get(zip_url)
        if resp.status_code != 200:
            raise DocParseError(f"下载解析结果失败 {resp.status_code}")

        md_content = None
        content_list = None
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in zf.namelist():
                if name.endswith(".md") and md_content is None:
                    md_content = zf.read(name).decode("utf-8", errors="ignore")
                elif name.endswith("_content_list.json"):
                    try:
                        content_list = __import__("json").loads(zf.read(name).decode("utf-8", errors="ignore"))
                    except Exception:
                        pass
        if not md_content:
            raise DocParseError("解析结果中未找到 Markdown 文件")
        return {"md_content": md_content, "content_list": content_list}


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
        result = await parse_batch_mineru_official(
            [{"name": filename, "content": file_content}],
            api_key=api_key,
            params=params,
        )
        item = result[0]
        if item["status"] != "success":
            raise DocParseError(item.get("error") or "解析失败")
        return item["md_content"]
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


async def parse_batch_mineru_official(
    files: List[Dict[str, Any]],
    api_key: Optional[str],
    params: dict,
    interval: float = 10.0,
    timeout: float = 3600.0,
    on_progress: Optional[Callable[[List[Dict[str, Any]]], Awaitable[None]]] = None,
) -> List[Dict[str, Any]]:
    """MinerU 官方API 批量解析：申请上传链接 -> 批量上传 -> 轮询 -> 下载解包

    Args:
        files: [{"name": 文件名, "content": 字节}]
        api_key: mineru.net 申请的 Token
        params: language / enable_ocr
        on_progress: 进度回调（收到的 items 透传）

    Returns:
        与输入同序的列表：{"name", "status": "success"|"failed", "md_content", "content_list", "error"}
    """
    if not api_key:
        raise DocParseError("MinerU官方API需要配置API Key（mineru.net 申请）")

    name_map = {f["name"]: f["name"] for f in files}
    results: List[Dict[str, Any]] = []

    client = MineruBatchClient(api_key)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
        batch_id = await client.submit(http, files, params)
        items = await client.poll(
            http, batch_id,
            interval=interval, timeout=timeout, on_progress=on_progress,
        )
        for item in items:
            # file_name 可能带路径前缀，用 data_id 对齐原始文件名
            raw_name = item.get("file_name") or ""
            name = name_map.get(raw_name, raw_name)
            if item.get("state") == "done":
                zip_url = item.get("full_zip_url")
                if not zip_url:
                    results.append({"name": name, "status": "failed", "error": "解析完成但未返回结果文件"})
                    continue
                try:
                    parsed = await client.fetch_result_zip(http, zip_url)
                    results.append({"name": name, "status": "success", **parsed})
                except DocParseError as e:
                    results.append({"name": name, "status": "failed", "error": str(e)})
            else:
                results.append({"name": name, "status": "failed",
                                "error": item.get("err_msg") or "解析失败"})
    return results


async def _parse_mineru_official(
    file_content: bytes,
    filename: str,
    api_key: Optional[str],
    params: dict,
) -> str:
    """MinerU 官方API 单文件解析（兼容旧调用，内部走批量接口）"""
    result = await parse_batch_mineru_official(
        [{"name": filename, "content": file_content}],
        api_key=api_key,
        params=params,
    )
    item = result[0]
    if item["status"] != "success":
        raise DocParseError(item.get("error") or "解析失败")
    return item["md_content"]
