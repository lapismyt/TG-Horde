import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.utils.markdown import hcode
from aiogram.enums import ParseMode
from stablehorde_api import StableHordeAPI, ActiveModelsRequest, GenerationInput, ModelGenerationInputStable, ModelPayloadLorasStable
import msgspec
import models
import datetime
import base64
import aiofiles
import aiohttp
import time
import re

with open("admin.txt") as f: admin = f.read().strip()
with open("horde_token.txt") as f: horde_api_key = f.read().strip()
with open("tg_token.txt") as f: token = f.read().strip()

dp = Dispatcher()
bot = Bot(token=token, parse_mode=ParseMode.HTML)

def parse_loras(text):
    with open("loras.txt", "r") as f:
        loras = f.read().strip().splitlines()
    for item in text.split():
        if item.split(":")[0] not in loras:
            return None
    return {item.split(":")[0]: float(item.split(":")[1]) for item in text.split()}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    f = open("users.mpk", "rb")
    users = msgspec.msgpack.decode(f.read(), type=models.Users)
    f.close()
    user = users.get_user(message.from_user.id)
    if user is None:
        user = models.User(id=message.from_user.id)
        users.all.append(user)
        users = msgspec.msgpack.encode(users)
        f = open("users.mpk", "wb")
        f.write(users)
        f.close()
    await message.answer("Привет! Я могу генерировать изображения по текстовому запросу. Если нужна помощь, пиши /help.")

@dp.message(Command("lora"))
async def cmd_lora(message: types.Message):
    if message.text.lower().strip() == "/lora":
        with open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode(f.read(), type=models.Users)
        user = users.get_user(message.from_user.id)
        loras = user.generation_settings.loras
        if len(loras) >= 1:
            resp = f"Активные LoRA:\n\n"
            for lora in loras:
                resp += f"{lora.name}:{lora.strength}\n"
            await message.answer(resp)
        else:
            await message.answer("У вас нет активных LoRA.")
        return None
    if message.text.lower().replace("/lora ", "") == "clear":
        with open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode(f.read(), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.loras = []
        with open("users.mpk", "wb") as f:
            f.write(msgspec.msgpack.encode(users))
        await message.answer("LoRA очищены")
        return None
    selected = parse_loras(message.text.replace("/lora ", ""))
    if selected is None:
        await message.answer("Ошибка! Не удалось найти LoRA.")
    else:
        loras = []
        for name in selected.keys():
            strength = selected[name]
            lora = models.LoraSettings(name, strength)
            loras.append(lora)
        with open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode(f.read(), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.loras = loras
        with open("users.mpk", "wb") as f:
            f.write(msgspec.msgpack.encode(users))
        resp = f"Активные LoRA:\n\n"
        for lora in loras:
            resp += f"{lora.name}:{lora.strength}\n"
        await message.answer(resp)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("Тут пока что ничего нет, пишите @LapisMYT")

@dp.message(Command("add_lora"))
async def cmd_add_lora(message: types.Message):
    if "civitai.com/models/" in message.text:
        await message.forward(admin)
        await message.answer("Спасибо! В ближайшее время мы добавим LoRA.")
    elif str(message.from_user.id) == admin:
        async with aiofiles.open("loras.txt", "a") as f:
            model_id = message.text.split()[1]
            await f.write(model_id + "\n")
            await message.answer("LoRA добавлена.")
    else:
        await message.answer("Использование:\n/add_lora <ссылка на CivitAI> [примечание от себя].")

@dp.message(Command("nsfw"))
async def cmd_nsfw(message: types.Message):
    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    user = users.get_user(message.from_user.id)
    if user.generation_settings.nsfw:
        user.generation_settings.nsfw = False
        await message.answer("NSFW режим выключен.")
    else:
        user.generation_settings.nsfw = True
        await message.answer("NSFW режим включён.")
    with open("users.mpk", "wb") as f:
        f.write(msgspec.msgpack.encode(users))

@dp.message(Command("getid"))
async def cmd_getid(message: types.Message):
    await message.answer(str(message.from_user.id))

@dp.message(Command("premium"))
async def cmd_premium(message: types.Message):
    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    user = users.get_user(message.from_user.id)
    if user.admin:
        usr = users.get_user(int(messsge.text.split()[1]))
        usr.premium = not user.premium
        with open("users.mpk", "wb") as f:
            f.write(msgspec.msgpack.encode(users))

@dp.message(Command("n"))
async def cmd_n(message: types.Message):
    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    user = users.get_user(message.from_user.id)
    if user.premium:
        user.generation_settings.n = int(message.text.split()[1])
    with open("users.mpk", "wb") as f:
        f.write(msgspec.msgpack.encode(users))

@dp.message(Command("model"))
async def cmd_model(message: types.Message):
    request = message.text.replace("/model ", "")
    active_models = await horde.get_models(ActiveModelsRequest())
    model = None
    possible = []
    for m in active_models:
        if m.name.lower() == request.lower():
            model = m.name
            break
        elif request.lower() in m.name.lower():
            possible.append(m.name)
    if model is not None:
        with open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode(f.read(), type=models.Users)
        user = users.get_user(message.from_user.id)
        await message.answer("Выбрана модель: " + model)
        with open("users.mpk", "wb") as f:
            users = msgspec.msgpack.encode(users)
            f.write(users)
    else:
        additional = f""
        if len(possible) >= 1:
            additional += f"Возможно, вы имели ввиду:\n"
            for pm in possible:
                additional += f"{pm}\n"
        await message.answer(f"Модель не найдена: {request}\n\n{additional}")

@dp.message(Command("image"))
async def cmd_image(message: types.Message):
    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    user = users.get_user(message.from_user.id)
    if user.queued:
        await message.answer("Сначала дождись окончания генерации.")
        return None
    if message.text == "/image":
        await message.answer("Нет запроса.")
    user.queued = True
    with open("users.mpk", "wb") as f:
        f.write(msgspec.msgpack.encode(users))
    msg = await message.answer("Подождите...")
    
    if user.generation_settings.loras is not None:
        loras = []
        for lora in user.generation_settings.loras:
            loras.append(ModelPayloadLorasStable(lora.name, model=lora.strength))
    else: loras = None

    params = ModelGenerationInputStable(
        sampler_name = "k_euler_a",
        cfg_scale = user.generation_settings.cfg_scale,
        height = user.generation_settings.height,
        width = user.generation_settings.width,
        steps = user.generation_settings.steps,
        karras = True,
        loras = loras,
        n = user.generation_settings.n
    )

    payload = GenerationInput(
        message.text.replace("/image ", ""),
        params = params,
        nsfw = user.generation_settings.nsfw,
        censor_nsfw = not user.generation_settings.nsfw,
        models = [user.generation_settings.model],
        r2 = True
    )

    request = await horde.txt2img_request(payload)
    await asyncio.sleep(5)
    status = await horde.generate_check(request.id)
    eta = status.wait_time
    position = status.queue_position

    response = f""
    response += f"Вы на {str(position)} месте в очереди.\n"
    response += f"Ожидайте ~{str(datetime.timedelta(seconds=eta))}.\n\n"
    response += f"ID запроса: {hcode(request.id)}."
    await msg.edit_text(response)

    finished = False
    while not finished:
        status = await horde.generate_check(request.id)
        if status.done == 1:
            finished = True
        else:
            await asyncio.sleep(status.wait_time)

    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    user = users.get_user(message.from_user.id)
    user.queued = False
    with open("users.mpk", "wb") as f:
        f.write(msgspec.msgpack.encode(users))

    img_status = await horde.generate_status(request.id)
    generations = img_status.generations
    await msg.delete()
    for num, generation in enumerate(generations):
        path = "{str(int(time.time()))}_{str(num)}.webp"
        await message.answer_photo(generation.img)
        async with aiohttp.ClientSession() as session:
            async with session.get(generation.img) as resp:
                async with aiofiles.open(path, "wb") as f:
                    f.write(await resp.content.read())

@dp.message(Command("models"))
async def cmd_models(message: types.Message):
    models = await horde.get_models(ActiveModelsRequest())
    models = sorted(models, key=lambda x: x.eta)
    sorted_models = []
    for model in models:
        if int(model.eta) > 0:
            sorted_models.append(model)
    sorted_models = sorted_models[:15]
    result = ""
    for model in sorted_models:
        result += f"{model.name}:\n"
        result += f"Количество воркеров: {str(model.count)}\n"
        result += f"Очередь: {str(int(model.queued) + int(model.jobs))}\n"
        result += f"Время генерации: >{str(datetime.timedelta(seconds=model.eta*200))}\n\n"
    await message.answer(result.strip())

async def main():
    global horde
    horde = StableHordeAPI(horde_api_key)
    logging.basicConfig(level=logging.INFO)
    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    for usr in users.all:
        usr.queued = False
    with open("users.mpk", "wb") as f:
        f.write(msgspec.msgpack.encode(users))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
