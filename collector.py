class DataCollector:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def collect_player(self, *args, **kwargs):
        raise RuntimeError("Local LCU collector has been removed. Use /cross_query instead.")

    def collect_match_and_players(self, *args, **kwargs):
        raise RuntimeError("Local LCU collector has been removed. Use /cross_query instead.")
