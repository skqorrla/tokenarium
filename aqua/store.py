# DataStore - ERD 설계 전 스텁
# TODO: ERD 확정 후 SQLite 스키마 및 CRUD 구현

class DataStore:
    def __init__(self, db_path: str = "aqua.db"):
        self.db_path = db_path

    def save_feed(self, feed_data):
        raise NotImplementedError

    def get_fish_states(self) -> list:
        raise NotImplementedError

    def update_fish_state(self, project_id: str, food_delta: float):
        raise NotImplementedError
