# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import asyncio
import json
import threading
from fastapi import APIRouter, Body
from pathlib import Path

from module.config.utils import write_file
from module.image.rpc import ensure_image_server_ready, get_image_client
from module.logger import logger
from module.server.api_logger import ApiLoggingRoute
from module.ocr.rpc import ensure_ocr_server_ready, get_ocr_client
from module.server.main_manager import MainManager
from module.server.updater import Updater
from module.server.i18n import I18n

home_app = APIRouter(
    prefix="/home",
    tags=["home"],
    route_class=ApiLoggingRoute,
)
update_info_lock = threading.Lock()


@home_app.get('/test')
async def home_test():
    return {'message': 'test'}


#  gcc -Wall -pedantic -shared -fPIC -o group_work.so group_work.c -lwiringPi
@home_app.get('/home_menu')
async def home_menu():
    return {'Home': [], 'Updater': [], 'Tool': []}


@home_app.get('/image_server_info')
async def image_server_info():
    ensure_image_server_ready()
    return get_image_client(refresh=True).get_server_info()


@home_app.get('/ocr_server_info')
async def ocr_server_info():
    ensure_ocr_server_ready()
    return get_ocr_client(refresh=True).get_server_info()


@home_app.post('/notify_test')
async def notify_test(setting: str, title: str, content: str):
    from module.notify.notify import Notifier
    try:
        notifier = Notifier(setting, True)
        if notifier.push(title=title, content=content):
            del notifier
            return True
        else:
            del notifier
            return False
    except Exception as e:
        logger.exception(e)
        return str(e)


@home_app.get('/kill_server')
async def kill_server():
    # 只置信号，由主循环在退出前关闭图像/OCR 服务，避免启动器等待子进程退出。
    MainManager.signal_kill_server = True
    return 'success'


@home_app.get('/update_info')
async def update_info():
    try:
        return await asyncio.to_thread(_get_update_info)
    except Exception as e:
        logger.error(e)
        return None


def _get_update_info():
    with update_info_lock:
        updater = Updater()
        return updater.get_update_info()


@home_app.get('/execute_update')
async def execute_update():
    # 下拉仓库 -> 关闭所有脚本进程 -> 最后重启oasx
    try:
        updater = Updater()
        updater.execute_pull()
    except Exception as e:
        logger.error(e)
    return '手动更新将会立即结束运行中的脚本服务, 最后你还需重启oasx'


@home_app.put('/chinese_translate')
async def chinese_translate(data: dict = Body(...)):
    try:
        I18n.save_zh_cn(data)
    except Exception as e:
        logger.error(e)
    return True


@home_app.get('/additional_translate')
async def additional_translate() -> dict:
    try:
        data = I18n.load_additions()
        return data
    except Exception as e:
        logger.error(e)
    return {}


@home_app.get('/export_diagnostic')
async def export_diagnostic(config_name: str = ''):
    from module.server.diagnostic import build_diagnostic_zip
    try:
        zip_path = build_diagnostic_zip(config_name)
        return {'success': True, 'path': str(zip_path)}
    except Exception as e:
        logger.exception(e)
        return {'success': False, 'path': '', 'error': str(e)}
