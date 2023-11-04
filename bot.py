import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.utils.markdown import hcode
from aiogram.enums import ParseMode
from aiogram.types import ContentType
from stablehorde_api import StableHordeAPI, ActiveModelsRequest, GenerationInput, ModelGenerationInputStable, ModelPayloadLorasStable, ModelPayloadTextualInversionsStable
from stablehorde_api.errors import *
import msgspec
import models
import datetime
import base64
import aiofiles
import aiohttp
import time
import re
import json
import random

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
    out = {item.split(":")[0]: float(item.split(":")[1]) for item in text.split()}
    if out == []: out = None
    return out

def load_tis(prompt):
    tis = []
    if " ### " in prompt:
        prompt, negprompt = prompt.split(" ### ")
    else: negprompt = None
    available = json.load(open("tis.json"))
    for ti in available.keys():
        if ti.lower() in prompt.lower():
            tis.append(
                ModelPayloadTextualInversionsStable(
                    name = available[ti],
                    inject_ti = "prompt"
                )
            )
        elif negprompt is not None:
            if ti.lower() in negprompt.lower():
                tis.append(
                    ModelPayloadTextualInversionsStable(
                        name = available[ti],
                        inject_ti = "negprompt"
                    )
                )
        else: pass
    if tis == []: tis = None
    return tis

@dp.message(Command("sendall"))
async def cmd_sendall(message: types.Message):
    if message.from_user.id == int(admin):
        with open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode(f.read(), type=models.Users)
        for usr in users.all:
            try:
                await message.reply_to_message.forward(usr.id)
            except:
                pass

@dp.message(Command("add_ti"))
async def cmd_add_ti(message: types.Message):
    if message.from_user.id == int(admin):
        with open("tis.json") as f:
            tis = json.load(f)
        tis[message.text.split()[1]] = message.text.split()[2]
        with open("tis.json", "w") as f:
            json.dump(tis, f)
        await message.answer("Magic TI добавлена!")

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
    elif str(message.from_user.id) == admin and message.text.split()[1].isdigit():
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
    if message.from_user.id == int(admin):
        usr = users.get_user(int(message.text.split()[1]))
        if not usr.premium:
            usr.premium = True
            await bot.send_message(usr.id, "У вас теперь есть премиум.")
            await message.answer(f"У пользователя {str(usr.id)} теперь есть премиум.")
        else:
            usr.premium = False
            await bot.send_message(usr.id, "У вас больше нету премиума.")
            await message.answer(f"У пользователя {str(usr.id)} больше нету премиума.")
        with open("users.mpk", "wb") as f:
            f.write(msgspec.msgpack.encode(users))

@dp.message(Command("res"))
async def cmd_res(message: types.Message):
    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    user = users.get_user(message.from_user.id)
    try:
        width, height = map(int, message.text.lower().split()[1].split('x'))
        if 64 <= (width * height) <= (768*768):
            user.generation_settings.width = width
            user.generation_settings.height = height
            with open("users.mpk", "wb") as f:
                f.write(msgspec.msgpack.encode(users))
    except:
        pass
    await message.answer(f"Текущее разрешение: {str(user.generation_settings.width)}x{str(user.generation_settings.height)}")

@dp.message(Command("n"))
async def cmd_n(message: types.Message):
    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    user = users.get_user(message.from_user.id)
    if len(message.text.split()) != 2:
        await message.answer("Количество генерируемых изображений за раз: " + str(user.generation_settings.n) + ".")
        return None
    if user.premium:
        n = int(message.text.split()[1])
        if 1 <= n <= 10:
            user.generation_settings.n = n
        await message.answer("Количество генерируемых изображений за раз: " + str(user.generation_settings.n) + ".")
    else:
        await message.answer("Для этого нужен премиум.")
    with open("users.mpk", "wb") as f:
        f.write(msgspec.msgpack.encode(users))

@dp.message(Command("pose"))
async def cmd_pose(message: types.Message):
    poses = os.listdir("poses")
    pose = message.text.split()[1].strip().lower()
    if pose == "clear":
        pose = None
    if not pose + ".jpg" in poses:
        await message.answer("Позы не существует!")
        return None
    with open("users.mpk", "rb+") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.pose = pose
        f.write(msgspec.msgpack.encode(users))
    await messsge.answer("Поза изменена.")

@dp.message(content_types=ContentType.PHOTO)
async def handle_photo(message: types.Message):
    if not str(message.from_user.id) == admin:
        return None
    photo = message.photo[-1]
    name = message.text.strip()
    await photo.download(f"poses/{name}.jpg")
    await message.answer("Поза успешно добавлена!")

@dp.message(Command("model"))
async def cmd_model(message: types.Message):
    request = message.text.replace("/model ", "")
    active_models = await horde.get_models(ActiveModelsRequest())
    model = None
    possible = []
    if message.text.lower() == "/model any":
        with open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode(f.read(), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.model = "ANY"
        with open("users.mpk", "wb") as f:
            f.write(msgspec.msgpack.encode(users))
        await message.answer("Выбрана модель: ANY")
        return None
    elif message.text.lower() == "/model":
        with open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode(f.read(), type=models.Users)
        user = users.get_user(message.from_user.id)
        if user.generation_settings.model.lower() == "any":
            model = "ANY"
        else:
            model = user.generation_settings.model
        await message.answer("Активная модель: " + model)
        return None
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
        user.generation_settings.model = model
        await message.answer("Выбрана модель: " + model)
        with open("users.mpk", "wb") as f:
            f.write(msgspec.msgpack.encode(users))
    else:
        additional = f""
        if len(possible) >= 1:
            additional += f"Возможно, вы имели ввиду:\n"
            for pm in possible:
                additional += f"{pm}\n"
        await message.answer(f"Модель не найдена: {request}\n\n{additional}")

@dp.message(Command("loras"))
async def cmd_loras(message: types.Message):
    file = types.input_file.FSInputFile("loras.txt")
    await message.answer_document(file)

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
        return None
    user.queued = True
    with open("users.mpk", "wb") as f:
        f.write(msgspec.msgpack.encode(users))
    msg = await message.answer("Подождите...")
    
    if user.generation_settings.loras is not None:
        loras = []
        for lora in user.generation_settings.loras:
            loras.append(ModelPayloadLorasStable(lora.name, model=lora.strength))
    else: loras = None

    tis = load_tis(message.text.replace("/image ", ""))

    source_image = None
    image_is_control = None
    control_type = None
    if user.generation_settings.pose is not None:
        source_image = horde.convert_image(user.generation_settings.pose)
        image_is_control = True
        control_type = "depth"

    params = ModelGenerationInputStable(
        sampler_name = user.generation_settings.sampler,
        cfg_scale = user.generation_settings.cfg_scale,
        height = user.generation_settings.height * 2,
        width = user.generation_settings.width * 2,
        steps = user.generation_settings.steps,
        karras = True,
        loras = loras,
        n = user.generation_settings.n,
        hires_fix = True,
        tis = tis,
        image_is_control = image_is_control,
        control_type = control_type
    )

    model = user.generation_settings.model
    if model.lower() == "any":
        model = None
    else:
        model = [model]

    payload = GenerationInput(
        prompt = message.text.replace("/image ", ""),
        params = params,
        nsfw = user.generation_settings.nsfw,
        censor_nsfw = not user.generation_settings.nsfw,
        models = model,
        r2 = True,
        slow_workers = False,
        source_image = source_image
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
        try:
            status = await horde.generate_check(request.id)
            eta = status.wait_time
            position = status.queue_position
            response = f""
            response += f"Вы на {str(position)} месте в очереди.\n"
            response += f"Ожидайте ~{str(datetime.timedelta(seconds=eta))}.\n\n"
            response += f"ID запроса: {hcode(request.id)}."
            try:
                await msg.edit_text(response)
            except:
                pass
        except StatusNotFound:
            with open("users.mpk", "rb") as f:
                users = msgspec.msgpack.decode(f.read(), type=models.Users)
            user = users.get_user(message.from_user.id)
            user.queued = False
            with open("users.mpk", "wb") as f:
                f.write(msgspec.msgpack.encode(users))
            await message.answer("Ошибка! Не удалось сгенерировать изображение.")
            return None
        if status.done == 1:
            finished = True
        else:
            await asyncio.sleep(5)

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
        path = f"images/{str(int(time.time()))}_{str(num)}.webp"
        await message.answer_photo(generation.img)
        async with aiohttp.ClientSession() as session:
            async with session.get(generation.img) as resp:
                async with aiofiles.open(path, "wb") as f:
                    f.write(await resp.content.read())

@dp.message(Command("steps"))
async def cmd_steps(message: types.Message):
    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    user = users.get_user(message.from_user.id)
    if message.text.lower() == "/steps":
        await message.answer("Шаги: " + str(user.generation_settings.steps))
    elif message.text.lower().split()[1].isdigit():
        if 1 <= int(message.text.lower().split()[1]) <= 500:
            user.generation_settings.steps = int(message.text.lower().split()[1])
        await message.answer("Шаги: " + str(user.generation_settings.steps))
    else:
        pass
    with open("users.mpk", "wb") as f:
        f.write(msgspec.msgpack.encode(users))

@dp.message(Command("cfg"))
async def cmd_steps(message: types.Message):
    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    user = users.get_user(message.from_user.id)
    if message.text.lower() == "/cfg":
        await message.answer("CFG Scale: " + str(user.generation_settings.cfg_scale))
    elif message.text.lower().split()[1].isdigit():
        if 0 <= int(message.text.lower().split()[1]) <= 100:
            user.generation_settings.cfg_scale = float(message.text.lower().split()[1])
        await message.answer("CFG Scale: " + str(user.generation_settings.cfg_scale))
    else:
            pass
    with open("users.mpk", "wb") as f:
        f.write(msgspec.msgpack.encode(users))

@dp.message(Command("kudos"))
async def cmd_kudos(message: types.Message):
    usr = await horde.find_user()
    await message.answer("Kudos: " + str(int(usr.kudos)))

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
        result += f"Время генерации: >{str(datetime.timedelta(seconds=model.eta))}\n\n"
    await message.answer(result.strip())

async def main():
    global horde
    horde = StableHordeAPI(horde_api_key, api="https://aihorde.net/api/v2")
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
