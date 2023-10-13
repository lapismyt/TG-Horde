import msgspec

class LoraSettings(msgspec.Struct):
    name: str
    strength: float = 0.85

class GenerationSettings(msgspec.Struct):
    width: int = 512
    height: int = 512
    cfg_scale: float = 7.0
    steps: int = 20
    loras: list[LoraSettings] | None = None
    nsfw: bool = False
    model: str = "any"
    n: int = 1
    sampler: str = "k_lms"

class User(msgspec.Struct):
    id: int
    premium: bool = False
    admin: bool = False
    generations_left: int = 10
    generation_settings: GenerationSettings = GenerationSettings()
    queued: bool = False

class Users(msgspec.Struct):
    all: list[User] = []
    premium: list[User] = []

    def get_user(self, id):
        user = None
        for usr in self.all:
            if usr.id == id:
                user = usr
                break
        return user
