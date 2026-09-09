# 应用级异常
class TaskCancelled(Exception):
    """协作式取消：长任务在批次边界检测到用户取消请求时抛出。

    由各 xxx_task 的异常收尾统一落库为 cancelled 状态，
    区别于普通失败（failed）——取消不是错误，不应计入失败率。
    """
