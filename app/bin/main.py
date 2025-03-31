import datetime
import time
import os
import threading
import numpy as np
import cv2
import glob
import configparser
import sys
import logging
from utils import CFEVideoConf, image_resize

config_file = configparser.ConfigParser()
config_file.optionxform = str

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(__file__)

config_path = os.path.join(application_path, 'config.ini')
config_file.read(config_path)

log_path = os.path.join(application_path, 'logs.txt')
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s',
                    handlers=[logging.FileHandler(log_path, encoding='utf-8'), logging.StreamHandler()])
print = logging.info

FRAMES_PER_SECOND = int(config_file['TIMELAPSE']['frames_per_seconds'])
SECONDS_DURATION = int(config_file['TIMELAPSE']['seconds_duration'])
SECONDS_BETWEEN_SHOTS = int(config_file['TIMELAPSE']['seconds_between_shots'])
DELETE_OLDER_THAN_DAYS = int(config_file['TIMELAPSE']['delete_images_older_than_days'])
BASE_OUTPUT_PATH = config_file['SETTINGS']['base_output_path']
TIMELAPSE_OUTPUT_PATH = config_file['SETTINGS']['timelapse_output_path']
CAMERAS = config_file['CAMERAS']

def setup_directories():
    os.makedirs(BASE_OUTPUT_PATH, exist_ok=True)
    os.makedirs(TIMELAPSE_OUTPUT_PATH, exist_ok=True)

def delete_old_images(camera_name):
    base = os.path.join(BASE_OUTPUT_PATH, camera_name.replace('___', ''), 'images')
    cutoff = time.time() - DELETE_OLDER_THAN_DAYS * 86400
    for root, _, files in os.walk(base):
        for f in files:
            path = os.path.join(root, f)
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                print("[DELETE]", path)
                os.remove(path)
    control_dir = os.path.join(BASE_OUTPUT_PATH, camera_name.replace('___', ''))
    for fname in os.listdir(control_dir):
        if fname.startswith("used_") and fname.endswith(".txt"):
            fpath = os.path.join(control_dir, fname)
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                print("[DELETE] Arquivo de controle antigo removido:", fpath)
                os.remove(fpath)

def capture_frames(camera_name, stream_url):
    print(f"[CAPTURA] Iniciando câmera: {camera_name}")
    next_capture = time.time()
    while True:
        now = time.time()
        if now < next_capture:
            time.sleep(0.1)
            continue

        today_str = datetime.datetime.now().strftime('%d-%m-%Y')
        image_dir = os.path.join(BASE_OUTPUT_PATH, camera_name.replace('___', ''), 'images', today_str)
        os.makedirs(image_dir, exist_ok=True)

        try:
            cap = cv2.VideoCapture(stream_url)
            if not cap.isOpened():
                print(f"[ERRO] Conexão {camera_name}")
                time.sleep(10)
                next_capture += SECONDS_BETWEEN_SHOTS
                continue

            for _ in range(5):
                cap.read()
            ret, frame = cap.read()
            cap.release()

            if not ret:
                print(f"[ERRO] Falha ao capturar imagem da câmera {camera_name}")
                time.sleep(5)
                next_capture += SECONDS_BETWEEN_SHOTS
                continue

            timestamp_str = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S-%f')[:-3] + "-03-00"
            filename = os.path.join(image_dir, f'{timestamp_str}.jpg')
            cv2.imwrite(filename, frame)
            print(f"[CAPTURA] Imagem salva: {camera_name.replace('___', '')}/images/{today_str}/" + os.path.basename(filename))

        except Exception as e:
            print(f"[EXCEPTION] Erro na câmera {camera_name}: {e}")

        next_capture += SECONDS_BETWEEN_SHOTS

def generate_timelapse(camera_name):
    today = datetime.datetime.now().strftime('%d-%m-%Y')
    image_dir = os.path.join(BASE_OUTPUT_PATH, camera_name.replace('___', ''), 'images', today)
    used_images_file = os.path.join(BASE_OUTPUT_PATH, camera_name.replace('___', ''), f"used_{today}.txt")

    os.makedirs(os.path.dirname(used_images_file), exist_ok=True)
    used_images = set()

    if os.path.exists(used_images_file):
        with open(used_images_file, 'r') as f:
            used_images = set(line.strip() for line in f if line.strip())

    all_images = sorted(glob.glob(os.path.join(image_dir, '*.jpg')))
    new_images = [img for img in all_images if os.path.basename(img) not in used_images]

    if not new_images:
        print(f"[INFO] Nenhuma imagem nova para {camera_name}")
        return

    first = image_resize(cv2.imread(new_images[0]), width=1280)
    h, w = first.shape[:2]
    ts = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S-%f')[:-3] + "-03-00"
    filename = f"{camera_name}{ts}.mp4"
    video_path = os.path.join(TIMELAPSE_OUTPUT_PATH, filename)
    out = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'mp4v'), FRAMES_PER_SECOND, (w, h))

    for img in new_images:
        frame = image_resize(cv2.imread(img), width=w)
        out.write(frame)

    out.release()
    print(f"[VIDEO] Gerado para {camera_name}: " + os.path.basename(video_path))

    with open(used_images_file, 'a') as f:
        for img in new_images:
            f.write(os.path.basename(img) + '\n')

    delete_old_images(camera_name)

def scheduler():
    while True:
        now = datetime.datetime.now()
        if now.hour == 23 and now.minute == 59:
            print("[SCHEDULER] Execução forçada às 23:59")
            for cam in CAMERAS:
                generate_timelapse(cam)
            time.sleep(60)
            continue

        print("[SCHEDULER] Esperando próximo ciclo...")
        time.sleep(SECONDS_DURATION)
        print("[SCHEDULER] Gerando timelapses...")
        for cam in CAMERAS:
            generate_timelapse(cam)

if __name__ == '__main__':
    setup_directories()
    for cam, url in CAMERAS.items():
        threading.Thread(target=capture_frames, args=(cam, url), daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("[ENCERRADO] Interrompido pelo usuário.")