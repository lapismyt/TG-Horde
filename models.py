import msgspec

class GenerationSettings(msgspec.Struct):
    width: int = 512
    height: int = 512
    cfg_scale: float = 7.5
    steps: int = 20
    loras: None | list[dict] = []
    nsfw: bool = False
    model: str = "ANY"
    n: int = 1
    sampler: str = "k_euler_a"
    pose: str | None = None
    hires_fix: bool = True
    strength: float = 0.7
    gif_prompt: str = "1girl ### EasyNegative, children"
    seed: int | str | None = None
    prompt_template: str = "{p}###{np}"
    tis: None | list[dict] = []

    def __post_init__(self):
        if self.loras is None:
            self.loras = []
        if self.tis is None:
            self.tis = []

class User(msgspec.Struct):
    id: int
    premium: bool = False
    admin: bool = False
    generations_left: int = 10
    generation_settings: GenerationSettings = GenerationSettings()
    queued: bool = False
    images_generated: int = 0

class Users(msgspec.Struct):
    all: list[User] = []
    total_images: int = 0
    premium: list[User] = []

    def get_user(self, id):
        user = None
        for usr in self.all:
            if usr.id == id:
                user = usr
                break
        return user
