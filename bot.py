import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram import F
from aiogram.utils.markdown import hcode
from aiogram.enums import ParseMode
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
import os, sys
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import shutil
from PIL import Image, ImageSequence
from aiogram.types.input_file import FSInputFile

with open("admin.txt") as f: admin = f.read().strip()
with open("horde_token.txt") as f: horde_api_key = f.read().strip()
with open("tg_token.txt") as f: token = f.read().strip()

dp = Dispatcher()
bot = Bot(token=token, parse_mode=ParseMode.HTML)
scheduler = AsyncIOScheduler()

samplers = ["k_lms", "k_heun", "k_euler", "k_euler_a", "k_dpm_2", "k_dpm_2_a", "k_dpm_fast", "k_dpm_adaptive", "k_dpmpp_2s_a", "k_dpmpp_2m", "dpmsolver", "k_dpmpp_sde", "ddim"]

def resize_image(filename):
    with Image.open(filename) as image:
        width, height = image.size
        new_width = (width // 64) * 64
        new_height = (height // 64) * 64
        resized_image = image.resize((new_width, new_height))
        resized_image.save(filename)

@dp.message(Command("copy"))
async def copy_db(message=None):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = await f.read()
    async with aiofiles.open(f"dbs/users-{round(time.time())}.mpk", "wb") as f:
        await f.write(users)

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

@dp.message(Command("strength"))
async def cmd_strength(message: types.Message):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    async with aiofiles.open("users.mpk", "wb") as f:
        try:
            strength = float(message.text.split()[1])
        except: return None
        user = users.get_user(message.from_user.id)
        user.generation_settings.strength = strength
        await f.write(msgspec.msgpack.encode(users))
    await message.answer("Сила: " + str(strength))

@dp.message(Command("sendall"))
async def cmd_sendall(message: types.Message):
    if message.from_user.id == int(admin):
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
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
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    if user is None:
        user = models.User(id=message.from_user.id)
        users.all.append(user)
        users = msgspec.msgpack.encode(users)
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(users)
    await message.answer("Привет! Я могу генерировать изображения по текстовому запросу. Но сначала...\n\nОБЯЗАТЕЛЬНО, ПРОЧИТАЙ РУКОВОДСТВО - /help")

@dp.message(Command("lora"))
async def cmd_lora(message: types.Message):
    if message.text.lower().strip() == "/lora":
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
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
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.loras = []
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(msgspec.msgpack.encode(users))
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
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.loras = loras
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(msgspec.msgpack.encode(users))
        resp = f"Активные LoRA:\n\n"
        for lora in loras:
            resp += f"{lora.name}:{lora.strength}\n"
        await message.answer(resp)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("https://telegra.ph/Kak-polzovatsya-HordeAI-Bot-10-21")

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
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    if user.generation_settings.nsfw:
        user.generation_settings.nsfw = False
        await message.answer("NSFW режим выключен.")
    else:
        user.generation_settings.nsfw = True
        await message.answer("NSFW режим включён.")
    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))

@dp.message(Command("hires_fix"))
async def cmd_nsfw(message: types.Message):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    if user.generation_settings.hires_fix:
        user.generation_settings.hires_fix = False
        await message.answer("HiRes Fix выключен.")
    else:
        user.generation_settings.hires_fix = True
        await message.answer("HiRes Fix включён.")
    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))

@dp.message(Command("getid"))
async def cmd_getid(message: types.Message):
    await message.answer(str(message.from_user.id))

@dp.message(Command("premium"))
async def cmd_premium(message: types.Message):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
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
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(msgspec.msgpack.encode(users))

@dp.message(Command("res"))
async def cmd_res(message: types.Message):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    try:
        width, height = map(int, message.text.lower().split()[1].split('x'))
        if 64 <= (width * height) <= (1024*2048):
            user.generation_settings.width = width
            user.generation_settings.height = height
            async with aiofiles.open("users.mpk", "wb") as f:
                await f.write(msgspec.msgpack.encode(users))
    except:
        pass
    await message.answer(f"Текущее разрешение: {str(user.generation_settings.width)}x{str(user.generation_settings.height)}")

@dp.message(Command("n"))
async def cmd_n(message: types.Message):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
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
    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))

@dp.message(F.gif)
async def handle_gif(message: types.Message):
    if not str(message.from_user.id) == str(admin):
        return None
    else:
        await message.answer("Падажи...")
    gif = message.document
    gif_index = int(time.time())
    filename = f"anim-{gif_index}.gif"
    folder = f"animations/{gif_index}"
    os.makedirs(folder)
    await bot.download(gif, filename)
    frames = []
    with Image.open(filename).convert("RGBA") as gif:
        for frame in ImageSequence.iterator(gif):
            frame.save(f"{folder}/{index}.jpg")
            resize_image(f"{folder}/{index}.jpg")
            frame = Image.open(f"{folder}/{index}.jpg").convert("RGBA")
            with Image.open(f"{folder}/{index}.jpg") as im:
                width = im.width
                height = im.height
            img = await horde.convert_image(f"{folder}/{index}.jpg")
            params = ModelGenerationInputStable(
                sampler_name = "k_euler_a",
                cfg_scale = 8,
                height = height,
                width = width,
                steps = 15,
                denoising_strength = 1.0,
                image_is_control = False,
                control_type = "canny",
                return_control_map = False,
                clip_skip = 2
            )
            payload = GenerationInput(
                prompt = " ",
                params = params,
                nsfw = True,
                censor_nsfw = False,
                models = None,
                r2 = True,
                slow_workers = False,
                source_image = img,
                source_processing = "img2img",
                replacement_filter = True
            )
            request = await horde.txt2img_request(payload)
            finished = False
            while not finished:
                status = await horde.generate_check(request.id)
                if status.done == 1:
                    finished = True
                else:
                    await asyncio.sleep(1)
            generated = await horde.generate_status(request.id).generations[0].img
            async with aiohttp.ClientSession() as session:
                async with session.get(generation.img) as resp: 
                    async with aiofiles.open(f"{folder}/{index}.webp", "wb") as f:
                        await f.write(await resp.content.read())
            frames.append(Image.open(f"{folder}/{index}.webp"))
            os.remove(f"{folder}/{index}.jpg")
            os.remove(f"{folder}/{index}.webp")
    os.remove(filename)
    frames[0].save(
        filename,
        save_all=True,
        append_images=frames[1:],
        optimize=True,
        duration=[gif.info["duration"] for x in range(len(frames))]
    )
    file = FSInputFile(filename)
    os.remove(filename)
    await bot.send_document(message.chat.id, file)

@dp.message(F.document)
async def handle_photo(message: types.Message):
    if message.document.mime_type == "video/mp4":
        await handle_gif(message)
        return None
    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    inpainting = False
    if hasattr(message, "caption"):
        if message.caption.startswith("inpainting: "):
            inpainting = True
    user = users.get_user(message.from_user.id)
    if not user.premium and inpainting:
        await message.answer("Для этого нужна премиум-подписка.")
        return None
    if not hasattr(message, "caption"):
        await message.answer("Нет запроса.")
        return None
    photo = message.document
    if "image" not in photo.mime_type:
        return None
    filename = photo.file_name
    await bot.download(photo, destination=f"img2img/{filename}")
    resize_image(f"img2img/{filename}")
    with Image.open(f"img2img/{filename}") as img:
        width = img.width
        height = img.height
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    if user.queued:
        await message.answer("Сначала дождись окончания генерации.")
        return None
    user.queued = True
    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))
    msg = await message.answer("Подождите...")
    
    if user.generation_settings.loras is not None:
        loras = []
        for lora in user.generation_settings.loras:
            loras.append(ModelPayloadLorasStable(lora.name, model=lora.strength))
    else: loras = None

    tis = load_tis(message.caption)

    control_types = ["canny", "depth", "lineart", "hed", "normal", "openpose", "seg", "scribble", "fakescribbles", "hough"]

    prompt = message.caption
    source_processing = None
    control_type = None
    image_is_control = False
    return_control_map = False

    if prompt.startswith("inpainting: "):
        prompt = prompt.removeprefix("inpainting: ")
        source_processing = "inpainting"
    elif prompt.startswith("get-"):
        prompt = prompt.removeprefix("get-")
        return_control_map = True

    for c in control_types:
        if prompt.startswith(f"{c}: "):
            prompt = prompt.removeprefix(f"{c}: ")
            control_type = c
            image_is_control = True
            break

    params = ModelGenerationInputStable(
#        sampler_name = user.generation_settings.sampler,
        sampler_name = "k_euler_a",
        cfg_scale = user.generation_settings.cfg_scale,
        height = height,
        width = width,
        steps = user.generation_settings.steps,
        loras = loras if not image_is_control else None,
        n = user.generation_settings.n,
#        post_processing = None,
        hires_fix = False,
        tis = tis if not image_is_control else None,
        denoising_strength = user.generation_settings.strength,
        image_is_control = False,
        control_type = control_type,
        return_control_map = return_control_map,
        clip_skip = 2
    )

    model = user.generation_settings.model
    if model.lower() == "any":
        model = None
    else:
        model = [model]

    payload = GenerationInput(
        prompt = prompt,
        params = params,
        nsfw = user.generation_settings.nsfw,
        censor_nsfw = not user.generation_settings.nsfw,
        models = model,
        r2 = True,
        slow_workers = False,
        source_image = await horde.convert_image(f"img2img/{filename}"),
        source_processing = source_processing,
        replacement_filter = True
    )
    try:
        request = await horde.txt2img_request(payload)
    except BaseException as err:
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.queued = False
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(msgspec.msgpack.encode(users))
            print(repr(err))
        await msg.edit_text("Ошибка!")
        return None
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
            async with aiofiles.open("users.mpk", "rb") as f:
                users = msgspec.msgpack.decode((await f.read()), type=models.Users)
            user = users.get_user(message.from_user.id)
            user.queued = False
            async with aiofiles.open("users.mpk", "wb") as f:
                await f.write(msgspec.msgpack.encode(users))
            await message.answer("Ошибка! Не удалось сгенерировать изображение.")
            return None
        if status.done == 1:
            finished = True
        else:
            await asyncio.sleep(5)

    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    user.queued = False
    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))

    img_status = await horde.generate_status(request.id)
    generations = img_status.generations
    await msg.delete()
    for num, generation in enumerate(generations):
        path = f"images/{str(int(time.time()))}_{str(num)}.webp"
        await message.answer_photo(generation.img)
        async with aiohttp.ClientSession() as session:
            async with session.get(generation.img) as resp:
                async with aiofiles.open(path, "wb") as f:
                    await f.write(await resp.content.read())

@dp.message(Command("model"))
async def cmd_model(message: types.Message):
    request = message.text.replace("/model ", "")
    active_models = await horde.get_models(ActiveModelsRequest())
    model = None
    possible = []
    if message.text.lower() == "/model any":
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.model = "ANY"
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(msgspec.msgpack.encode(users))
        await message.answer("Выбрана модель: ANY")
        return None
    elif message.text.lower() == "/model":
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
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
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.model = model
        await message.answer("Выбрана модель: " + model)
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(msgspec.msgpack.encode(users))
    else:
        additional = f""
        if len(possible) >= 1:
            additional += f"Возможно, вы имели ввиду:\n"
            for pm in possible:
                additional += f"{pm}\n"
        await message.answer(f"Модель не найдена: {request}\n\n{additional}")

@dp.message(Command("sampler"))
async def cmd_sampler(message: types.Message):
    global samplers
    if message.text.lower().strip().replace("/sampler ", "") in samplers:
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.sampler = message.text.lower().strip().replace("/sampler ", "")
        if user.generation_settings.sampler == "ddim":
            user.generation_settings.sampler = "DDIM"
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(msgspec.msgpack.encode(users))
        await message.answer("Сэмплер изменён.")
    else:
        await message.answer("Сэмплер не найден.\nДоступные сэмплеры:\n"+"\n".join(samplers))

@dp.message(Command("loras"))
async def cmd_loras(message: types.Message):
    file = types.input_file.FSInputFile("loras.txt")
    await message.answer_document(file)

@dp.message(Command("image"))
async def cmd_image(message: types.Message):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    if user.queued:
        await message.answer("Сначала дождись окончания генерации.")
        return None
    if message.text == "/image":
        await message.answer("Нет запроса.")
        return None
    user.queued = True
    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))
    msg = await message.answer("Подождите...")
    
    if user.generation_settings.loras is not None:
        loras = []
        for lora in user.generation_settings.loras:
            loras.append(ModelPayloadLorasStable(lora.name, model=lora.strength))
    else: loras = None

    tis = load_tis(message.text.replace("/image ", ""))

    params = ModelGenerationInputStable(
        sampler_name = user.generation_settings.sampler,
        cfg_scale = user.generation_settings.cfg_scale,
        height = user.generation_settings.height,
        width = user.generation_settings.width,
        steps = user.generation_settings.steps,
        loras = loras,
        n = user.generation_settings.n,
        post_processing = ["CodeFormers", "RealESRGAN_x4plus"],
        hires_fix = user.generation_settings.hires_fix,
        tis = tis,
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
        replacement_filter = True
    )
    try:
        request = await horde.txt2img_request(payload)
    except BaseException as err:
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.queued = False
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(msgspec.msgpack.encode(users))
        print(repr(err))
        await msg.edit_text("Ошибка!")
        return None
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
            async with aiofiles.open("users.mpk", "rb") as f:
                users = msgspec.msgpack.decode((await f.read()), type=models.Users)
            user = users.get_user(message.from_user.id)
            user.queued = False
            async with aiofiles.open("users.mpk", "wb") as f:
                await f.write(msgspec.msgpack.encode(users))
            await message.answer("Ошибка! Не удалось сгенерировать изображение.")
            return None
        if status.done == 1:
            finished = True
        else:
            await asyncio.sleep(5)

    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    user.queued = False
    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))

    img_status = await horde.generate_status(request.id)
    generations = img_status.generations
    await msg.delete()
    for num, generation in enumerate(generations):
        path = f"images/{str(int(time.time()))}_{str(num)}.webp"
        await message.answer_photo(generation.img)
        async with aiohttp.ClientSession() as session:
            async with session.get(generation.img) as resp:
                async with aiofiles.open(path, "wb") as f:
                    await f.write(await resp.content.read())

@dp.message(Command("steps"))
async def cmd_steps(message: types.Message):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    if message.text.lower() == "/steps":
        await message.answer("Шаги: " + str(user.generation_settings.steps))
    elif message.text.lower().split()[1].isdigit():
        if 1 <= int(message.text.lower().split()[1]) <= 500:
            user.generation_settings.steps = int(message.text.lower().split()[1])
        await message.answer("Шаги: " + str(user.generation_settings.steps))
    else:
        pass
    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))

@dp.message(Command("cfg"))
async def cmd_steps(message: types.Message):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    if message.text.lower() == "/cfg":
        await message.answer("CFG Scale: " + str(user.generation_settings.cfg_scale))
    elif message.text.lower().split()[1].isdigit():
        if 0 <= int(message.text.lower().split()[1]) <= 100:
            user.generation_settings.cfg_scale = float(message.text.lower().split()[1])
        await message.answer("CFG Scale: " + str(user.generation_settings.cfg_scale))
    else:
        pass
    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))

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
    global scheduler
    horde = StableHordeAPI(horde_api_key, api="https://aihorde.net/api/v2")
    logging.basicConfig(level=logging.INFO)
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    for usr in users.all:
        usr.queued = False
    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
