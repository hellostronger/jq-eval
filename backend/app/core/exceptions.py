# 应用级异常
def format_error(exc: BaseException) -> str:
    """把异常格式化成可落库/展示的错误文本，保证非空。

    网络类异常（httpx.ConnectError 等）的 str() 往往为空字符串，
    直接 str(e) 会让任务"失败但没有任何原因"，用户只看到一个空的
    error 字段、无从排查。此处兜底为异常类名，保证错误信息始终可见。

    注意：str(exc) 非空时本函数与 str(exc) 完全等价，因此可以放心地
    机械替换所有落库/展示用的 str(e)。
    """
    text = str(exc).strip()
    return text if text else type(exc).__name__


class TaskCancelled(Exception):
    """协作式取消：长任务在批次边界检测到用户取消请求时抛出。

    由各 xxx_task 的异常收尾统一落库为 cancelled 状态，
    区别于普通失败（failed）——取消不是错误，不应计入失败率。
    """
