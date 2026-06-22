class LCUConnectionError(RuntimeError):
    pass


class LCUClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def connect(self) -> None:
        raise LCUConnectionError("Local LCU query has been removed. Use /cross_query instead.")

    def get_summoner_by_name(self, *args, **kwargs):
        raise LCUConnectionError("Local LCU query has been removed. Use /cross_query instead.")

    def get_match_history(self, *args, **kwargs):
        raise LCUConnectionError("Local LCU query has been removed. Use /cross_query instead.")

    def get_match_detail(self, *args, **kwargs):
        raise LCUConnectionError("Local LCU query has been removed. Use /cross_query instead.")

    def get_rank(self, *args, **kwargs) -> str:
        return ""
