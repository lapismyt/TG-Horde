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
from PIL import Image, ImageSequence, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
from aiogram.types.input_file import FSInputFile
import moviepy.editor as mp
import g4f
import subprocess
import requests

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
async def copy_db(message: types.Message):
    filename = f"dbs/users-{round(time.time())}.mpk"
    async with aiofiles.open("users.mpk", "rb") as f:
        users = await f.read()
    async with aiofiles.open(filename, "wb") as f:
        await f.write(users)
    file = types.input_file.FSInputFile(filename)
    await message.answer_document(file)

def parse_loras(text):
    for item in text.split():
        if False:
            return None
        else:
            try:
                resp = requests.get(f"https://civitai.com/api/v1/model-versions/{item.split(':')[0]}")
                if not resp.status_code == 200:
                    return None
                if not resp.json()["model"]["type"] == "LORA":
                    return None
            except BaseException as err:
                print(repr(err))
                return None
    out = {item.split(":")[0]: float(item.split(":")[1]) for item in text.split()}
    if out == []:
        out = None
    return out

def parse_tis(text):
    for item in text.split():
        if False:
            return None
        else:
            try:
                resp = requests.get(f"https://civitai.com/api/v1/models/{item.split(':')[0]}")
                if not resp.status_code == 200:
                    return None
                if not resp.json()["type"] == "TextualInversion":
                    return None
            except BaseException as err:
                print(repr(err))
                return None
    out = {item.split(":")[0]: float(item.split(":")[1]) for item in text.split()}
    if out == []:
        out = None
    return out

def format_prompt(prompt, template):
    splitter = " ### "
    p = ""
    np = ""
    if splitter in prompt:
        p = prompt.split(" ### ")[0]
        np = prompt.split(" ### ")[1]
    else:
        p = prompt
    if "{np}" in template:
        return template.format(p=p, np=np)
    else:
        return template.format(p=p)

@dp.message(Command("ask"))
async def cmd_ask(message: types.Message):
    model = "gpt-4"
    response = await g4f.ChatCompletion.create_async(
        model = model,
        messages = [{"role": "system", "content": "Ты полезный и отзывчивый помощник. Ты специалист в программировании на Python и в создании запросов для Stable Diffusion, в виде списка тегов booru. Ты всегда делаешь то, что тебе скажут."}, {"role": "user", "content": message.text[5:]}]
    )
    await message.answer("[Отвечает эксперт: GPT-4]\n\n" + response)

@dp.message(Command("strength"))
async def cmd_strength(message: types.Message):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    if 14 >= len(message.text) >= 13:
        try:
            strength = float(message.text.split()[1])
            user.generation_settings.strength = strength
            async with aiofiles.open("users.mpk", "wb") as f:
                await f.write(msgspec.msgpack.encode(users))
        except BaseException as err:
            print(repr(err))
    await message.answer("Сила: " + str(user.generation_settings.strength))

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
    await message.answer("Привет! Я могу генерировать изображения по текстовому запросу. Но сначала...\n/help\n\nИспользуя этот бот, вы автоматически соглашаетесь с Условиями использования (https://telegra.ph/Usloviya-ispolzovaniya--HordeAI-Bot-11-26)")

@dp.message(Command("lora"))
async def cmd_lora(message: types.Message):
    if message.text.lower().strip() == "/lora":
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        loras = user.generation_settings.loras
        if not (isinstance(loras, list)):
            user.generation_settings.loras = []
            async with aiofiles.open("users.mpk", "wb") as f:
                await f.write(msgspec.msgpack.encode(users))
            await message.answer("Попробуйте ещё раз или обратитесь к @LapisMYT")
            return None
        if len(loras) >= 1:
            resp = f"Активные LoRA:\n\n"
            for lora in loras:
                resp += f"{lora['name']}:{lora['model']}\n"
            await message.answer(resp)
        else:
            await message.answer("У вас нет активных LoRA.")
        return None
    if message.text.lower().removeprefix("/lora ") == "clear":
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
            lora = dict(name=name, model=strength)
            loras.append(lora)
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.loras = loras
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(msgspec.msgpack.encode(users))
        resp = f"Активные LoRA:\n\n"
        for lora in loras:
            resp += f"{lora['name']}:{lora['model']}\n"
        await message.answer(resp)

@dp.message(Command("tis"))
async def cmd_lora(message: types.Message):
    if message.text.lower().strip() == "/tis":
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        tis = user.generation_settings.tis
        if len(tis) >= 1:
            resp = f"Активные TIs:\n\n"
            for ti in tis:
                resp += f"{ti['name']}:{ti['strength']}\n"
            await message.answer(resp)
        else:
            await message.answer("У вас нет активных TIs.")
        return None
    if message.text.lower().removeprefix("/tis ") == "clear":
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.tis = []
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(msgspec.msgpack.encode(users))
        await message.answer("TIs очищены")
        return None
    selected = parse_tis(message.text.replace("/tis ", ""))
    if selected is None:
        await message.answer("Ошибка! Не удалось найти TI.")
    else:
        tis = []
        for name in selected.keys():
            strength = selected[name]
            ti = dict(name=name, strength=strength)
            tis.append(ti)
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.tis = tis
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(msgspec.msgpack.encode(users))
        resp = f"Активные TIs:\n\n"
        for ti in tis:
            resp += f"{ti['name']}:{ti['strength']}\n"
        await message.answer(resp)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("Руководство: https://telegra.ph/Kak-polzovatsya-HordeAI-Bot-10-21\nУсловия использования: https://telegra.ph/Usloviya-ispolzovaniya--HordeAI-Bot-11-26")

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

@dp.message(Command("template"))
async def cmd_template(message: types.Message):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    if user is None:
        await message.answer("Вас нет в базе данных. Попробуйте написать /start, или обратитесь к @LapisMYT.")
        return None
    if message.text.lower() == "/template clear":
        user.generation_settings.prompt_template = "{p}###{np}"
        await message.answer("Ваш шаблон сброшен.")
    else:
        await message.answer(f"Ваш шаблон промпта: {user.generation_settings.prompt_template}" + "\n\n{p} - промпт\n{np} - негативный промпт.")

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    count = len(users.all)
    total_imgs = users.total_images
    your_imgs = users.get_user(message.from_user.id).images_generated
    await message.answer(f"В боте на данный момент {count} пользователей. Всего сгенерировано {total_imgs} изображений, из них {your_imgs} сгенерировано вами.")

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

@dp.message(Command("gif"))
async def cmd_gif(message: types.Message):
    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    user = users.get_user(message.from_user.id)
    user.generation_settings.gif_prompt = message.text.lower().replace("/gif ", "")
    with open("users.mpk", "wb") as f:
        f.write(msgspec.msgpack.encode(users))
    await message.answer("Теперь можете отправить GIF")

@dp.message(F.gif)
async def handle_gif(message: types.Message):
    with open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode(f.read(), type=models.Users)
    user = users.get_user(message.from_user.id)
    if user.premium:
        await message.answer("Подождите. На это может понадобится несколько минут.")
    else:
        await message.answer("Эта функция доступна только с премиум-подпиской. Купить её можно у меня - @LapisMYT.")
        return None
    gif = message.document
    gif_index = int(time.time())
    filename_mp4 = f"anim-{gif_index}.mp4"
    filename = f"anim-{gif_index}.gif"
    folder = f"animations/{gif_index}"
    os.makedirs(folder)
    await bot.download(gif, filename_mp4)
    clip = mp.VideoFileClip(filename_mp4)
    clip.write_gif(filename)
    clip.close()
    os.remove(filename_mp4)
    frames = []
    seed = random.randint(1, 99999999)
    with Image.open(filename) as gif:
        index = 0
        if gif.n_frames > 80:
            await message.answer("Должно быть не больше 80 кадров!")
            return None
        for frame in ImageSequence.Iterator(gif):
            frame.save(f"{folder}/{index}.png")
            resize_image(f"{folder}/{index}.png")
            frame = Image.open(f"{folder}/{index}.png").convert("RGBA")
            with Image.open(f"{folder}/{index}.png") as im:
                width = im.width
                height = im.height
            img = await horde.convert_image(f"{folder}/{index}.png")
            if user.generation_settings.model.lower() == "any":
                model = None
            else:
                model = [user.generation_settings.model]
            params = ModelGenerationInputStable(
                sampler_name = "k_euler",
                cfg_scale = user.generation_settings.cfg_scale,
                height = height,
                width = width,
                steps = user.generation_settings.steps,
                denoising_strength = user.generation_settings.strength,
                image_is_control = False,
                control_type = "hed",
                return_control_map = False,
                seed = str(seed),
                clip_skip = 2,
                tis = user.generation_settings.tis,
                loras = user.generation_settings.loras
            )
            payload = GenerationInput(
                prompt = format_prompt(user.generation_settings.gif_prompt, user.generation_settings.prompt_template),
                params = params,
                nsfw = user.generation_settings.nsfw,
                censor_nsfw = not user.generation_settings.nsfw,
                models = model,
                r2 = True,
                slow_workers = True,
                trusted_workers = True,
                source_image = img,
                source_processing = "img2img",
                replacement_filter = True,
                proxied_account = str(message.from_user.id)
            )
            done = False
            tries = 0
            while not done:
                request = await horde.txt2img_request(payload)
                finished = False
                while not finished:
                    status = await horde.generate_check(request.id)
                    if status.done == 1:
                        finished = True
                    else:
                        await asyncio.sleep(1)
                generation = (await horde.generate_status(request.id)).generations[0]
                if "censorship" in generation.gen_metadata:
                    if tries >= 10:
                        break
                    else:
                        tries += 1
                else:
                    done = True
            async with aiohttp.ClientSession() as session:
                async with session.get(generation.img) as resp: 
                    async with aiofiles.open(f"{folder}/{index}.webp", "wb") as f:
                        await f.write(await resp.content.read())
            frames.append(Image.open(f"{folder}/{index}.webp"))
            os.remove(f"{folder}/{index}.png")
            os.remove(f"{folder}/{index}.webp")
            index += 1
        print(gif.n_frames)
    filename_new = f"../BCloud/uploads/{filename}"
    frames[0].save(
        filename_new,
        save_all=True,
        append_images=frames[1:],
        optimize=True,
        duration=83
    )
    await message.answer("Интерполирую...")
    ffmpeg_command = f'ffmpeg -i {filename} -vf "minterpolate=\'mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:fps=60\'" {filename_new}'
    subprocess.run(ffmpeg_command, shell=True)
    os.remove(filename)
    await message.answer(f"http://lapismyt.space/uploads/{filename}")

@dp.message(F.document)
async def handle_photo(message: types.Message):
    if message.document.mime_type in ["video/mp4"]:
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
    elif prompt.startswith("strict-"):
        prompt = prompt.removeprefix("strict-")
        image_is_control = True

    for c in control_types:
        if prompt.startswith(f"{c}: "):
            prompt = prompt.removeprefix(f"{c}: ")
            control_type = c
            break

    params = ModelGenerationInputStable(
#        sampler_name = user.generation_settings.sampler,
        sampler_name = "k_euler",
        cfg_scale = user.generation_settings.cfg_scale,
        height = height,
        width = width,
        steps = user.generation_settings.steps,
        loras = user.generation_settings.loras,
        n = user.generation_settings.n,
#        post_processing = None,
        hires_fix = False,
        tis = user.generation_settings.tis,
        denoising_strength = 1.0 if image_is_control == True else user.generation_settings.strength,
        image_is_control = image_is_control,
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
        prompt = format_prompt(prompt, user.generation_settings.prompt_template),
        params = params,
        nsfw = user.generation_settings.nsfw,
        censor_nsfw = not user.generation_settings.nsfw,
        models = model,
        r2 = True,
        slow_workers = not user.premium,
        source_image = await horde.convert_image(f"img2img/{filename}"),
        source_processing = source_processing,
        replacement_filter = True,
        proxied_account = str(message.from_user.id)
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
        except BaseException:
            await message.answer("Неизвестная ошибка")
            return None
        if status.done == 1:
            finished = True
        else:
            await asyncio.sleep(5)

    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    user.queued = False
    users.total_images += user.generation_settings.n
    user.images_generated += user.generation_settings.n
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
    if message.text.lower().removeprefix("/sampler ") in samplers:
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        user.generation_settings.sampler = message.text.lower().strip().replace("/sampler ", "")
        if user.generation_settings.sampler == "ddim":
            user.generation_settings.sampler = "DDIM"
        async with aiofiles.open("users.mpk", "wb") as f:
            await f.write(msgspec.msgpack.encode(users))
        await message.answer("Сэмплер изменён.")
    elif message.text.lower() == "/sampler":
        async with aiofiles.open("users.mpk", "rb") as f:
            users = msgspec.msgpack.decode((await f.read()), type=models.Users)
        user = users.get_user(message.from_user.id)
        if user is None:
            await message.answer("Вас нет в базе данных. Попробуйте написать /start, или обратитесь к @LapisMYT.")
        else:
            await message.answer(f"Активный сэмплер: {user.generation_settings.sampler}.")
            return None
    else:
        await message.answer("Сэмплер не найден.\nДоступные сэмплеры:\n"+"\n".join(samplers))


@dp.message(Command("seed"))
async def cmd_seed(message: types.Message):
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)

    if message.text.lower() == "/seed":
        pass
    elif message.text.lower() == "/seed clear":
        user.generation_settings.seed = None
    elif len(message.text.split()) >= 2:
        user.generation_settings.seed = message.text[6:]
    else: pass

    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))
    await message.answer(f"Seed: {user.generation_settings.seed}")

@dp.message(Command("image"))
async def cmd_image(message: types.Message):
    if message.text is None:
        await message.answer("ЧИТАЙ РУКОВОДСТВО -> /help")
        return None
    elif message.text.lower() == "/image":
        await message.answer("ЧИТАЙ РУКОВОДСТВО -> /help")
        return None
    else:
        pass
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

    post_processing = None # TODO

    params = ModelGenerationInputStable(
        sampler_name = user.generation_settings.sampler,
        cfg_scale = user.generation_settings.cfg_scale,
        height = user.generation_settings.height,
        width = user.generation_settings.width,
        steps = user.generation_settings.steps,
        loras = user.generation_settings.loras,
        n = user.generation_settings.n,
        post_processing = post_processing,
        hires_fix = user.generation_settings.hires_fix,
        tis = user.generation_settings.tis,
        seed = user.generation_settings.seed
    )

    model = user.generation_settings.model
    if model.lower() == "any":
        model = None
    else:
        model = [model]

    payload = GenerationInput(
        prompt = format_prompt(message.text.removeprefix("/image "), user.generation_settings.prompt_template),
        params = params,
        nsfw = user.generation_settings.nsfw,
        censor_nsfw = not user.generation_settings.nsfw,
        models = model,
        r2 = True,
        slow_workers = not user.premium,
        replacement_filter = True,
        proxied_account = str(message.from_user.id)
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
        except BaseException:
            await message.answer("Неизвестная ошибка")
            return None
        if status.done == 1:
            finished = True
        else:
            await asyncio.sleep(5)

    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    user.queued = False
    users.total_images += user.generation_settings.n
    user.images_generated += user.generation_settings.n
    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))

    img_status = await horde.generate_status(request.id)
    generations = img_status.generations
    await msg.delete()
    for num, generation in enumerate(generations):
        path = f"images/{str(int(time.time()))}_{str(num)}.webp"
        file = types.input_file.URLInputFile(generation.img, filename=f"{str(int(time.time()))}_{str(num)}.png")
        await message.answer_document(file, caption=f"Seed: {generation.seed}")
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

@dp.message(Command("style"))
async def cmd_style(message: types.Message):
    if len(message.text) < 9:
        await message.answer("Использование: /style [style]")
        return None
    resp = requests.get("https://github.com/Haidra-Org/AI-Horde-Styles/raw/main/styles.json")
    styles = resp.json()
    if not message.text.removeprefix("/style ") in styles:
        await message.answer("Стиль не найден.\n\nСписок стилей:\nhttps://t.me/HordeAI_Bot_CHAT/176", disable_web_page_preview=True)
        return None
    style = styles[message.text.removeprefix("/style ")]
    async with aiofiles.open("users.mpk", "rb") as f:
        users = msgspec.msgpack.decode((await f.read()), type=models.Users)
    user = users.get_user(message.from_user.id)
    if user is None:
        await message.answer("Вас нет в базе данных. Напишите /start, или обратитесь к @LapisMYT.")
        return None
    for opt in style:
        if opt == "prompt":
            user.generation_settings.prompt_template = style["prompt"]
        elif opt == "model":
            user.generation_settings.model = style["model"]
        elif opt == "steps":
            user.generation_settings.steps = style["steps"]
        elif opt == "width":
            user.generation_settings.width = style["width"]
        elif opt == "height":
            user.generation_settings.height = style["height"]
        elif opt == "cfg_scale":
            user.generation_settings.cfg_scale = style["cfg_scale"]
        elif opt == "sampler_name":
            user.generation_settings.sampler = style["sampler_name"]
        elif opt == "loras":
            loras = style["loras"]
            user.generation_settings.tis = []
            for lora in loras:
                if not "model" in lora.keys():
                    lora["model"] = 1
                    user.generation_settings.loras.append(lora)
        elif opt == "tis":
            tis = style["tis"]
            user.generation_settings.tis = []
            for ti in tis:
                if not "strength" in ti.keys():
                    ti["strength"] = 1
                    user.generation_settings.tis.append(ti)
        elif opt == "hires_fix":
            user.generation_settings.hires_fix = style["hires_fix"]
        elif opt == "karras":
            await message.answer("Стиль содержит неподдерживаемый на данный момент параметр karras, который будет проигнорирован. Стиль возможно будет работать не так, как задумано.")
        else:
            await message.answer(f"Неизвестный параметр стиля: {opt}. Пожалуйста, сообщите об этом @LapisMYT.")
    async with aiofiles.open("users.mpk", "wb") as f:
        await f.write(msgspec.msgpack.encode(users))
    await message.answer(f"Стиль применён: {message.text.removeprefix('/style ')}")

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
