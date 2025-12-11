import sys
import argparse
import os
import time
import traceback
import platform
import subprocess
import threading
import io
import base64
import json
import shlex
import socket

# ==========================================
# 🛑 ログ出力の強制設定
# ==========================================
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

print("🚀 アプリケーションの初期化を開始します...")

# ==========================================
# 🛑 エラー時の待機関数
# ==========================================
def wait_before_exit():
    print("\n" + "="*60)
    print("⚠️  プログラムを終了します。")
    print("エンターキーを押すとウィンドウを閉じます...")
    print("="*60 + "\n")
    try:
        input()
    except:
        pass

# ==========================================
# 空いているポートを探す関数
# ==========================================
def find_available_port(start_port):
    """
    指定されたポートから順に、利用可能な（空いている）ポートを探して返す関数
    """
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                # 0.0.0.0 (すべてのインターフェース) でバインドできるか試す
                sock.bind(('0.0.0.0', port))
                return port  # 成功したらそのポート番号を返す
            except OSError:
                # 失敗したら（すでに使われていたら）、次の番号へ
                port += 1
    return start_port

# ==========================================
# 📦 ライブラリ読み込み
# ==========================================
try:
    print("📦 ライブラリを読み込んでいます...")
    import gradio as gr
    import requests
    from PIL import Image, PngImagePlugin 
    from deep_translator import GoogleTranslator
    print("✅ 全てのライブラリ読み込み完了")
except ImportError as e:
    print(f"❌ エラー: 必要なライブラリが見つかりません。\n詳細: {e}")
    wait_before_exit()
    sys.exit(1)
except Exception as e:
    print(f"❌ 予期せぬエラー (Import中): {e}")
    print(traceback.format_exc())
    wait_before_exit()
    sys.exit(1)

# 全体をtryブロックで囲む
try:
    print("⚙️ 設定を読み込んでいます...")

    # ==========================================
    # ⚙️ 設定ファイル管理 (Config)
    # ==========================================
    CONFIG_FILE_PATH = os.path.join(os.path.expanduser("~"), ".artassist_config.json")
    
    DEFAULT_SETTINGS = {
        "sd_host": "http://127.0.0.1",
        "sd_port": "7860",
        "sd_webui_path": os.environ.get("SD_WEBUI_PATH", "/Applications/Data/Packages/Stable Diffusion WebUI"),
        "boot_args": "",
        "output_dir": ""
    }

    def load_settings():
        settings = DEFAULT_SETTINGS.copy()
        if os.path.exists(CONFIG_FILE_PATH):
            try:
                with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if "sd_url" in loaded and "sd_host" not in loaded:
                        url_parts = loaded["sd_url"].split(":")
                        if len(url_parts) >= 3:
                            loaded["sd_port"] = url_parts[-1]
                            loaded["sd_host"] = ":".join(url_parts[:-1])
                    for k, v in settings.items():
                        if k in loaded: settings[k] = loaded[k]
            except Exception as e:
                print(f"⚠️ 設定ファイルの読み込みに失敗: {e}")
        return settings

    def save_settings_to_file(host, port, webui_path, boot_args, output_dir):
        host = host.strip().rstrip("/")
        new_settings = {
            "sd_host": host,
            "sd_port": str(port).strip(),
            "sd_webui_path": webui_path.strip(),
            "boot_args": boot_args.strip(),
            "output_dir": output_dir.strip()
        }
        try:
            with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(new_settings, f, indent=4, ensure_ascii=False)
            
            update_globals(new_settings)
            return "" 
        except Exception as e:
            return f"❌ 保存エラー: {e}"

    def reset_settings_ui():
        default_path = os.path.join(os.path.expanduser("~"), "Pictures", "ArtAssist_Output")
        return (
            DEFAULT_SETTINGS["sd_host"],
            DEFAULT_SETTINGS["sd_port"],
            DEFAULT_SETTINGS["sd_webui_path"],
            DEFAULT_SETTINGS["boot_args"],
            default_path 
        )

    def refresh_settings_ui():
        return (SD_HOST, SD_PORT, SD_WEBUI_PATH, SD_BOOT_ARGS, BASE_OUTPUT_DIR)

    def update_globals(settings):
        global SD_HOST, SD_PORT, SD_WEBUI_PATH, SD_BOOT_ARGS, CURRENT_SD_URL, BASE_OUTPUT_DIR
        SD_HOST = settings["sd_host"]
        SD_PORT = settings["sd_port"]
        SD_WEBUI_PATH = settings["sd_webui_path"]
        SD_BOOT_ARGS = settings["boot_args"]
        CURRENT_SD_URL = f"{SD_HOST}:{SD_PORT}"
        
        if settings["output_dir"]:
            BASE_OUTPUT_DIR = settings["output_dir"]
        else:
            BASE_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "ArtAssist_Output")

    CURRENT_SETTINGS = load_settings()
    update_globals(CURRENT_SETTINGS)
    
    # ==========================================
    # ⚙️ グローバル変数
    # ==========================================
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", action="store_true")
    args, unknown = parser.parse_known_args()
    DEV_MODE = args.dev

    # 8000番から探し始め、空いていなければ 8001, 8002... と自動でずれます
    APP_PORT = find_available_port(8000)
    print(f"ℹ️ アプリケーションのポートを {APP_PORT} に設定しました")

    TARGET_MODEL_KEYWORD = "waiNSFWIllustrious" 
    SYSTEM_LOGS = []
    IGNORED_LOGS = ["画像を保存しました"]
    API_TIMEOUT = 600
    STARTING = False
    
    # 実行中のタスク状態管理
    CURRENT_TASK = None
    CURRENT_BATCH_INDEX = 0  # 現在何枚目を生成中か (0始まり)
    TOTAL_BATCH_COUNT = 1    # 全体の生成枚数
    EXPECTED_JOB_COUNT = 1   # 予定される工程数（ADありなら2など）
    LAST_BATCH_INDEX = -1    # 画像が切り替わったか判定用
    LAST_PROGRESS = 0.0      # 直前の進捗％（逆行防止用）
    LAST_LOGS_TEXT = None

    # ==========================================
    # 🛠️ ユーティリティ関数
    # ==========================================
    def add_log(message):
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        print(entry)
        is_ignored = any(x in message for x in IGNORED_LOGS)
        if DEV_MODE or not is_ignored:
            SYSTEM_LOGS.append(entry)
            if len(SYSTEM_LOGS) > 100: SYSTEM_LOGS.pop(0)

    def get_logs_text(): return "\n".join(SYSTEM_LOGS)

    def image_to_base64(image_path):
        with open(image_path, "rb") as img_file: return base64.b64encode(img_file.read()).decode('utf-8')

    def base64_to_image(b64_string):
        if isinstance(b64_string, str) and ',' in b64_string: b64_payload = b64_string.split(',', 1)[1]
        else: b64_payload = b64_string
        return Image.open(io.BytesIO(base64.b64decode(b64_payload)))

    def resize_for_sd(image_path, max_size=2048):
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        scale = 1.0
        if max(w, h) > max_size: scale = max_size / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        new_w, new_h = new_w - (new_w % 8), new_h - (new_h % 8)
        if scale != 1.0 or (w % 8 != 0) or (h % 8 != 0):
            img = img.resize((new_w, new_h), Image.LANCZOS)
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        b64_string = base64.b64encode(buffered.getvalue()).decode('utf-8')
        return b64_string, new_w, new_h

    def translate_and_optimize_prompt(jp_text):
        quality_tags = "masterpiece, best quality"
        negative_tags = "bad quality, worst quality, worst detail"
        if not jp_text: return quality_tags, negative_tags
        try:
            en_text = GoogleTranslator(source='ja', target='en').translate(jp_text)
            add_log(f"翻訳完了: {jp_text} -> {en_text}")
        except Exception as e:
            en_text = jp_text
            add_log("翻訳失敗 (原文を使用)")
        return f"{en_text}, {quality_tags}", negative_tags

    def ensure_adetailer_models():
        if not SD_WEBUI_PATH or not os.path.exists(SD_WEBUI_PATH):
            return 
        models_dir = os.path.join(SD_WEBUI_PATH, "models", "adetailer")

    def create_safe_ad_args(model, strength):
        return {
            "ad_model": model,
            "ad_denoising_strength": float(strength),
            "ad_confidence": 0.3
        }

    def save_generated_image(image, parameters=None):
        try:
            today_str = time.strftime("%Y-%m-%d")
            save_path = os.path.join(BASE_OUTPUT_DIR, today_str)
            os.makedirs(save_path, exist_ok=True)
            filename = f"gen_{int(time.time())}_{id(image)}.png"
            full_path = os.path.join(save_path, filename)
            pnginfo_data = PngImagePlugin.PngInfo()
            if parameters: pnginfo_data.add_text("parameters", parameters)
            image.save(full_path, pnginfo=pnginfo_data)
            return full_path
        except Exception as e:
            add_log(f"保存エラー: {e}")
            return None

    def open_output_folder():
        today_str = time.strftime("%Y-%m-%d")
        path = os.path.join(BASE_OUTPUT_DIR, today_str)
        if not os.path.exists(path):
            path = BASE_OUTPUT_DIR
            os.makedirs(path, exist_ok=True)
        try:
            system_name = platform.system()
            if system_name == "Windows": os.startfile(path)
            elif system_name == "Darwin": subprocess.Popen(["open", path])
            else: subprocess.Popen(["xdg-open", path])
            return f"📂 {path} を開きました"
        except Exception as e: return f"⚠️ エラー: {e}"

    # ==========================================
    # 🤖 システム制御
    # ==========================================
    def try_connect(url):
        try:
            r = requests.get(f"{url}/sdapi/v1/progress", timeout=3, proxies={"http": None, "https": None})
            return (True, "OK") if r.status_code == 200 else (False, f"Status {r.status_code}")
        except Exception as e: return False, str(e)

    def check_server_status():
        global CURRENT_SD_URL
        target_url = f"{SD_HOST}:{SD_PORT}"
        success, msg = try_connect(target_url)
        if success:
            if CURRENT_SD_URL != target_url: CURRENT_SD_URL = target_url
            return "🟢 起動中"
        return "🔴 停止中"

    def interrupt_generation():
        try:
            add_log("⚠️ 生成中止リクエストを送信...")
            requests.post(f"{CURRENT_SD_URL}/sdapi/v1/interrupt", proxies={"http": None, "https": None})
            global CURRENT_TASK
            CURRENT_TASK = None 
            return "中止しました"
        except Exception as e:
            return f"中止エラー: {e}"

    def poll_status():
        global LAST_PROGRESS, LAST_LOGS_TEXT, CURRENT_TASK, CURRENT_BATCH_INDEX, TOTAL_BATCH_COUNT, EXPECTED_JOB_COUNT, LAST_BATCH_INDEX
        
        status = check_server_status()
        logs = get_logs_text()
        
        # 進捗計算用の変数
        current_percent = 0.0
        job_info = ""
        is_generating = (CURRENT_TASK is not None)

        try:
            if "起動中" in status:
                r = requests.get(f"{CURRENT_SD_URL}/sdapi/v1/progress", timeout=1, proxies={"http": None, "https": None})
                if r.status_code == 200:
                    data = r.json()
                    
                    api_progress = data.get('progress') or 0.0
                    state = data.get('state') or {}
                    
                    job_count = state.get('job_count') or 1
                    job_no = state.get('job_no') or 0

                    # ★修正1: API初期値異常のガード
                    # 最初の画像の生成初期(5%未満)で job_no が進んでいたら、APIの誤報とみなして0に補正
                    if CURRENT_BATCH_INDEX == 0 and api_progress < 0.05 and job_no > 0:
                        job_no = 0

                    if api_progress > 0.001 or is_generating:
                        
                        # --- 📐 進捗計算ロジック ---
                        current_image_progress = 0.0

                        if CURRENT_TASK == 'face_fix':
                            if job_no == 0:
                                current_image_progress = 0.0
                            else:
                                current_image_progress = (api_progress - 0.5) / 0.5
                        else:
                            actual_job_count = max(job_count, EXPECTED_JOB_COUNT)
                            safe_job_no = min(job_no, actual_job_count - 1)
                            current_image_progress = (safe_job_no + api_progress) / max(1, actual_job_count)

                        current_image_progress = max(0.0, min(1.0, current_image_progress))

                        # 全体進捗
                        raw_percent = (CURRENT_BATCH_INDEX + current_image_progress) / max(1, TOTAL_BATCH_COUNT) * 100.0
                        
                        # ★★★ 逆行防止ロジック (修正版) ★★★
                        if LAST_BATCH_INDEX == CURRENT_BATCH_INDEX:
                            if raw_percent < LAST_PROGRESS:
                                delta = LAST_PROGRESS - raw_percent
                                # ★修正2: 差分判定のロジック変更
                                # 差が小さい(10%未満)なら「ただのブレ」として値を維持(逆行防止)
                                # 差が大きい(10%以上)なら「前の50%が異常値だった」とみなして、下がった値を許容する
                                if delta < 10.0:
                                    current_percent = LAST_PROGRESS
                                else:
                                    current_percent = raw_percent
                            else:
                                current_percent = raw_percent
                        else:
                            current_percent = raw_percent
                            LAST_BATCH_INDEX = CURRENT_BATCH_INDEX

                        display_percent = min(99.0, max(0.0, current_percent))
                        
                        LAST_PROGRESS = display_percent
                        job_info = f" ({CURRENT_BATCH_INDEX + 1}/{TOTAL_BATCH_COUNT}枚目) {int(display_percent)}%"
        except:
            pass
        
        val = 100 if (not is_generating and LAST_PROGRESS > 0) else int(LAST_PROGRESS)
        
        # UI更新
        btn_cleanup_update = gr.update(value="実行 ➡", interactive=True)
        btn_face_fix_update = gr.update(value="実行 ➡", interactive=True)
        btn_stop_update = gr.update(visible=False)      
        btn_stop_face_update = gr.update(visible=False) 
        style_out = ""

        if is_generating:
            if CURRENT_TASK == 'cleanup':
                label = f"✨ 生成中...{job_info}"
                btn_cleanup_update = gr.update(value=label, interactive=False)
                btn_face_fix_update = gr.update(interactive=False)
                btn_stop_update = gr.update(visible=True)
                btn_stop_face_update = gr.update(visible=False)
                style_out = f"""<style>#btn_cleanup {{ background: linear-gradient(90deg, #6366f1 {val}%, #e0e7ff {val}%) !important; pointer-events: none !important; }}</style>"""
            
            elif CURRENT_TASK == 'face_fix':
                label = f"✨ 生成中...{job_info}" 
                btn_cleanup_update = gr.update(interactive=False)
                btn_face_fix_update = gr.update(value=label, interactive=False)
                btn_stop_update = gr.update(visible=False)
                btn_stop_face_update = gr.update(visible=True)
                style_out = f"""<style>#btn_face_fix {{ background: linear-gradient(90deg, #6366f1 {val}%, #e0e7ff {val}%) !important; pointer-events: none !important; }}</style>"""
        
        else:
            style_out = """<style>#btn_cleanup, #btn_face_fix { background: linear-gradient(to bottom, #4f46e5, #4338ca) !important; pointer-events: auto !important; }</style>"""

        btn_server_update = gr.update(interactive=False, value="🚀 起動中...") if STARTING else (gr.update(interactive=False, value="✅ 起動済み") if "起動中" in status else gr.update(interactive=True, value="🚀 サーバー起動"))
        logs_out = logs if LAST_LOGS_TEXT != logs else gr.update()
        if logs_out != gr.update(): LAST_LOGS_TEXT = logs
        
        return (
            status, CURRENT_SD_URL, logs_out, 
            btn_server_update, 
            btn_cleanup_update, btn_stop_update, 
            btn_face_fix_update, btn_stop_face_update, 
            style_out
        )

    def start_sd_server():
        global STARTING
        def_ret = (
            gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
        )

        if not SD_WEBUI_PATH or not os.path.exists(SD_WEBUI_PATH):
            add_log(f"エラー: WebUIパス不明: {SD_WEBUI_PATH}")
            return ("⚠️ パスエラー", CURRENT_SD_URL, get_logs_text(), gr.update(interactive=True, value="🚀 サーバー起動"), *def_ret[4:])

        if STARTING or "起動中" in check_server_status():
            return ("処理中", CURRENT_SD_URL, get_logs_text(), gr.update(), *def_ret[4:])

        try:
            ensure_adetailer_models()

            add_log("サーバー起動コマンドを送信します")
            env = os.environ.copy()
            env["BROWSER"] = ":"
            env["NO_BROWSER"] = "1"
            env["GRADIO_BROWSER"] = "false"
            
            if platform.system() == "Windows":
                cmd = ["webui-user.bat", "--api", "--nowebui", "--port", str(SD_PORT)]
            else:
                cmd = ["bash", "webui.sh", "--api", "--nowebui", "--port", str(SD_PORT)]

            if SD_BOOT_ARGS and SD_BOOT_ARGS.strip():
                try:
                    cmd.extend(shlex.split(SD_BOOT_ARGS))
                except: pass
            
            subprocess.Popen(cmd, cwd=SD_WEBUI_PATH, env=env)
            add_log("サーバー起動中...")

            STARTING = True
            def _wait_for_start(timeout=120):
                global STARTING
                start = time.time()
                while time.time() - start < timeout:
                    if "起動中" in check_server_status():
                        STARTING = False
                        add_log("サーバー起動確認！")
                        return
                    time.sleep(1)
                STARTING = False
                add_log("タイムアウト")

            threading.Thread(target=_wait_for_start, daemon=True).start()
            return ("🚀 起動中...", CURRENT_SD_URL, get_logs_text(), gr.update(interactive=False, value="🚀 起動中..."), *def_ret[4:])
        except Exception as e:
            add_log(f"起動エラー: {e}")
            return (f"エラー: {str(e)}", CURRENT_SD_URL, get_logs_text(), gr.update(interactive=True, value="🚀 サーバー起動"), *def_ret[4:])

    def set_model_if_needed():
        try:
            opt_res = requests.get(f"{CURRENT_SD_URL}/sdapi/v1/options", proxies={"http": None, "https": None})
            current_model = opt_res.json().get("sd_model_checkpoint", "")
            if TARGET_MODEL_KEYWORD in current_model: return True
            
            models_res = requests.get(f"{CURRENT_SD_URL}/sdapi/v1/sd-models", proxies={"http": None, "https": None})
            target = next((m["title"] for m in models_res.json() if TARGET_MODEL_KEYWORD in m["title"] or TARGET_MODEL_KEYWORD in m["model_name"]), None)
            
            if target:
                requests.post(f"{CURRENT_SD_URL}/sdapi/v1/options", json={"sd_model_checkpoint": target}, proxies={"http": None, "https": None})
                add_log(f"モデルを変更しました: {target}")
                return True
            else:
                err_msg = f"❌ エラー: モデル '{TARGET_MODEL_KEYWORD}' が見つかりません。\nCivitai等からダウンロードして models/Stable-diffusion フォルダに入れてください。"
                add_log(err_msg)
                raise gr.Error(err_msg)
        except Exception as e:
            if isinstance(e, gr.Error): raise e
            return False

    def cleanup_sketch(image_path, hint_text, batch_count, denoise_label, ad_mode, seed):
        global CURRENT_TASK, CURRENT_BATCH_INDEX, TOTAL_BATCH_COUNT, EXPECTED_JOB_COUNT, LAST_BATCH_INDEX, LAST_PROGRESS

        if "停止中" in check_server_status(): raise gr.Error("SDサーバーをAPIモードで起動してください")
        
        # 初期化
        CURRENT_TASK = 'cleanup'
        TOTAL_BATCH_COUNT = int(batch_count)
        CURRENT_BATCH_INDEX = 0
        LAST_BATCH_INDEX = -1
        LAST_PROGRESS = 0.0
        
        # 予定工程数の設定
        EXPECTED_JOB_COUNT = 1
        if ad_mode == "顔のみ" or ad_mode == "手のみ":
            EXPECTED_JOB_COUNT = 2
        elif ad_mode == "顔と手":
            EXPECTED_JOB_COUNT = 3
            
        ensure_adetailer_models()
        set_model_if_needed()
        
        if image_path is None: 
            CURRENT_TASK = None
            yield [], "", gr.update(), None, gr.update(interactive=True, value="実行 ➡")
            return
        
        add_log("ラフ画チェック 画像生成開始...")
        prompt, neg_prompt = translate_and_optimize_prompt(hint_text)
        
        strength_map = {"弱": 0.3, "中": 0.4, "強": 0.5}
        d_strength = strength_map.get(denoise_label, 0.4)

        start_time = time.time()
        
        try:
            init_img_b64, w, h = resize_for_sd(image_path, max_size=2048)
            
            alwayson_scripts = {}
            ad_args = [True] 
            
            if ad_mode == "顔のみ":
                ad_args.append(create_safe_ad_args("face_yolov8s.pt", d_strength))
                ad_args.append({"ad_model": "None"})
            elif ad_mode == "手のみ":
                ad_args.append(create_safe_ad_args("hand_yolov8n.pt", d_strength))
                ad_args.append({"ad_model": "None"})
            elif ad_mode == "顔と手":
                ad_args.append(create_safe_ad_args("face_yolov8s.pt", d_strength))
                ad_args.append(create_safe_ad_args("hand_yolov8n.pt", d_strength))
                
            if len(ad_args) > 1: 
                alwayson_scripts["ADetailer"] = {"args": ad_args}

            gen_images = []
            parameters_list = []
            
            if isinstance(image_path, str): orig_img = Image.open(image_path).convert("RGB")
            else: orig_img = image_path.convert("RGB")

            for i in range(int(batch_count)):
                if CURRENT_TASK is None:
                    add_log("⛔️ ユーザー操作により生成を中止しました")
                    break

                CURRENT_BATCH_INDEX = i
                
                # -1ならランダム(API任せ)、固定値なら枚数ごとに+1して絵が被らないようにする
                req_seed = int(seed)
                if req_seed != -1:
                    req_seed = req_seed + i

                payload = {
                    "init_images": [init_img_b64], 
                    "prompt": prompt, 
                    "negative_prompt": neg_prompt,
                    "denoising_strength": d_strength, 
                    "seed": req_seed,
                    "steps": 20, 
                    "width": w, 
                    "height": h,
                    "cfg_scale": 7, 
                    "sampler_name": "Euler a",
                    "scheduler": "Automatic", 
                    "batch_size": 1, 
                    "alwayson_scripts": alwayson_scripts
                }
                
                res = requests.post(f"{CURRENT_SD_URL}/sdapi/v1/img2img", json=payload, timeout=API_TIMEOUT, proxies={"http": None, "https": None})

                if res.status_code == 422 and "Script 'ADetailer' not found" in res.text:
                    raise gr.Error("❌ ADetailer が見つかりません。")

                if res.status_code == 200:
                    json_data = res.json()
                    if 'images' in json_data:
                        for b64 in json_data['images']:
                            img = base64_to_image(b64)
                            info_txt = json.loads(json_data.get("info", "{}")).get("infotexts", [""])[0]
                            parameters_list.append(info_txt)
                            saved_path = save_generated_image(img, parameters=info_txt)
                            gen_images.append(saved_path if saved_path else img)
                    
                    yield gen_images, parameters_list, gr.update(visible=True), orig_img, gr.update(value=f"生成中... ({i+1}/{batch_count})", interactive=False)
                
                else: 
                    raise gr.Error(f"API Error: {res.status_code}")

            add_log(f"画像生成完了 ({time.time() - start_time:.1f}秒) - {len(gen_images)}枚")

            CURRENT_TASK = None
            yield gen_images, parameters_list, gr.update(visible=True), orig_img, gr.update(interactive=True, value="実行 ➡")

        except Exception as e:
            CURRENT_TASK = None
            add_log(f"処理中止または通信エラー: {e}")
            yield [], [], gr.update(visible=False), None, gr.update(interactive=True, value="実行 ➡")

    def fix_face_only(image_path, hint_text, batch_count, denoise_label, seed):
        global CURRENT_TASK, CURRENT_BATCH_INDEX, TOTAL_BATCH_COUNT, LAST_PROGRESS, LAST_BATCH_INDEX, EXPECTED_JOB_COUNT
        
        if "停止中" in check_server_status(): raise gr.Error("SDサーバーを起動してください")
        
        # 初期化
        CURRENT_TASK = 'face_fix'
        TOTAL_BATCH_COUNT = int(batch_count)
        CURRENT_BATCH_INDEX = 0
        LAST_BATCH_INDEX = -1
        LAST_PROGRESS = 0.0
        
        EXPECTED_JOB_COUNT = 2

        ensure_adetailer_models()
        set_model_if_needed()
        
        if image_path is None:
            CURRENT_TASK = None
            yield [], "", gr.update(), None, gr.update(interactive=True, value="実行 ➡")
            return
        
        add_log("顔チェック 画像生成開始...")
        prompt, neg_prompt = translate_and_optimize_prompt(hint_text)
        
        strength_map = {"弱": 0.3, "中": 0.5, "強": 0.7}
        ad_strength = strength_map.get(denoise_label, 0.5)
        
        start_time = time.time()
        
        try:
            init_img_b64, w, h = resize_for_sd(image_path, max_size=2048)
            
            alwayson_scripts = {
                "ADetailer": {
                    "args": [
                        True, 
                        create_safe_ad_args("face_yolov8s.pt", ad_strength),
                        {"ad_model": "None"} 
                    ]
                }
            }
            
            gen_images = []
            parameters_list = []

            if isinstance(image_path, str): orig_img = Image.open(image_path).convert("RGB")
            else: orig_img = image_path.convert("RGB")

            for i in range(int(batch_count)):
                if CURRENT_TASK is None:
                    add_log("⛔️ ユーザー操作により生成を中止しました")
                    break

                CURRENT_BATCH_INDEX = i

                # -1ならランダム(API任せ)、固定値なら枚数ごとに+1して絵が被らないようにする
                req_seed = int(seed)
                if req_seed != -1:
                    req_seed = req_seed + i

                payload = {
                    "init_images": [init_img_b64], 
                    "prompt": prompt, 
                    "negative_prompt": neg_prompt,
                    "denoising_strength": 0.0, 
                    "seed": req_seed,
                    "steps": 20,
                    "width": w, 
                    "height": h,
                    "cfg_scale": 7, 
                    "sampler_name": "Euler a",
                    "scheduler": "Automatic", 
                    "batch_size": 1, 
                    "alwayson_scripts": alwayson_scripts
                }
                
                res = requests.post(f"{CURRENT_SD_URL}/sdapi/v1/img2img", json=payload, timeout=API_TIMEOUT, proxies={"http": None, "https": None})

                if res.status_code == 422 and "Script 'ADetailer' not found" in res.text:
                    raise gr.Error("❌ ADetailer が見つかりません。")

                if res.status_code == 200:
                    json_data = res.json()
                    if 'images' in json_data:
                        for b64 in json_data['images']:
                            img = base64_to_image(b64)
                            info_txt = json.loads(json_data.get("info", "{}")).get("infotexts", [""])[0]
                            parameters_list.append(info_txt)
                            saved_path = save_generated_image(img, parameters=info_txt)
                            if saved_path:
                                gen_images.append(saved_path)
                            else:
                                gen_images.append(img)
                    
                    yield gen_images, parameters_list, gr.update(visible=True), orig_img, gr.update(value=f"生成中... ({i+1}/{batch_count})", interactive=False)
                else: 
                    raise gr.Error(f"API Error: {res.status_code}")
                
            add_log(f"画像生成完了 ({time.time() - start_time:.1f}秒) - {len(gen_images)}枚")
            CURRENT_TASK = None
            yield gen_images, parameters_list, gr.update(visible=True), orig_img, gr.update(interactive=True, value="実行 ➡")

        except Exception as e:
            CURRENT_TASK = None
            add_log(f"処理中止または通信エラー: {e}")
            yield [], [], gr.update(visible=False), None, gr.update(interactive=True, value="実行 ➡")


    def toggle_view(mode, gen_images, orig_img):
        count = len(gen_images) if gen_images else 1
        cols = 1 
        
        if mode == "生成画":
            imgs = [orig_img.copy() for _ in range(count)]
            return gr.update(value=imgs, columns=cols), "元画像"
        else:
            return gr.update(value=gen_images, columns=cols), "生成画"

    # ギャラリーで選択された画像のインデックスを取得する関数
    def on_gallery_select(evt: gr.SelectData):
        return evt.index

    def get_selected_param(params_list, index):
        if params_list and isinstance(params_list, list) and 0 <= index < len(params_list):
            return params_list[index]
        return "パラメータ情報がありません、または画像が選択されていません。"

    # ==========================================
    # UI状態のリセット関数
    # ==========================================
    def reset_ui_state():
        global CURRENT_BATCH_INDEX, LAST_PROGRESS, LAST_BATCH_INDEX
        # 前回の値を即座に消去する
        CURRENT_BATCH_INDEX = 0
        LAST_PROGRESS = 0.0
        LAST_BATCH_INDEX = -1
        # 実行ボタンを準備中に変える
        return gr.update(value="⏳ 準備中...", interactive=False)

    # ==========================================
    # 🖥️ UI構築
    # ==========================================
    custom_css = """
    footer {display: none !important;}
    .gradio-container {min-height: 0px !important;}
    .control-panel { display: flex !important; flex-direction: column !important; justify-content: center !important; gap: 10px !important; }
    #btn_cleanup, #btn_face_fix { height: 80px !important; font-size: 1.2em !important; background: linear-gradient(to bottom, #4f46e5, #4338ca) !important; color: white !important; border-radius: 12px !important; line-height: 1.2 !important; }
    
    #sd_server_frame { 
        border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; 
        background-color: #f8fafc; margin-bottom: 24px; position: relative !important;
    }
    #btn_settings {
        position: absolute !important; top: 10px !important; right: 10px !important;
        width: 36px !important; height: 36px !important; background: transparent !important;
        border: none !important; font-size: 20px !important; color: #9ca3af !important; z-index: 10 !important;
    }
    #btn_settings:hover { color: #4b5563 !important; transform: rotate(45deg); background-color: #e5e7eb !important; border-radius: 50% !important; }
    
    .server-btn { height: 50px !important; font-weight: bold !important; border-radius: 8px !important; }
    
    /* === ギャラリー表示修正 === */
    #output_image_wrapper { 
        position: relative !important;
        height: auto !important; 
        min-height: 400px;
    }
    
    #output_img button, #output_face_gallery button {
        overflow: visible !important;
    }
    
    #output_img img, #output_face_gallery img {
        display: block !important;
        object-fit: contain !important;
        width: 100% !important;
        height: auto !important;
        max-height: 600px !important; 
        background-color: #f3f4f6;
    }
    
    #btn_stop, #btn_stop_face {
        background-color: #ef4444 !important; color: white !important; border: none !important;
    }
    #btn_stop:hover, #btn_stop_face:hover { background-color: #dc2626 !important; }
    
    #info_btn, #info_btn_2 { 
        position: absolute !important; 
        bottom: 5px !important; 
        right: 5px !important; 
        z-index: 9999 !important; 
        width: 32px !important; 
        height: 32px !important; 
        background: rgba(255, 255, 255, 0.9) !important; 
        border-radius: 8px !important;
        border: 1px solid #e5e7eb !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important;
    }
        
    .modal-container {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0, 0, 0, 0.5); z-index: 10000;
        display: flex; justify-content: center; align-items: center;
        backdrop-filter: blur(2px);
    }
    .modal-content {
        background: white; padding: 25px; border-radius: 12px;
        box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
        width: 500px; max-width: 90%; max-height: 80vh;
        overflow-y: auto; display: flex; flex-direction: column; gap: 15px;
    }
    .settings-row { display: flex !important; flex-direction: row !important; align-items: center !important; gap: 8px !important; }
    """

    with gr.Blocks(title="FgG ArtAssist", css=custom_css, theme=gr.themes.Soft()) as demo:
        gr.Markdown("### 🎨 FgG ArtAssist - イラスト制作支援ツール β版")

        with gr.Column(elem_id="sd_server_frame"):
            btn_settings = gr.Button("⚙️", elem_id="btn_settings")
            gr.Markdown("#### Stable Diffusion サーバー（SDサーバー）")
            with gr.Row():
                with gr.Column(scale=2):
                    with gr.Row():
                        status_display = gr.Textbox(label="状態", value=check_server_status(), interactive=False)
                        sd_url_display = gr.Textbox(label="接続先", value=CURRENT_SD_URL, interactive=False)
                    with gr.Row():
                        btn_start_server = gr.Button("🚀 サーバー起動", variant="primary", elem_classes="server-btn")
                        btn_refresh = gr.Button("🔄 更新", variant="secondary", elem_classes="server-btn")
                with gr.Column(scale=3):
                    logs_display = gr.Textbox(label="ログ", value=get_logs_text(), lines=5, max_lines=5, interactive=False, autoscroll=True)

        with gr.Group(visible=False) as modal_settings:
            with gr.Group(elem_classes="modal-container"):
                with gr.Column(elem_classes="modal-content"):
                    gr.Markdown("### 🛠️ SDサーバー設定")
                    with gr.Row():
                        input_sd_host = gr.Textbox(label="WebUI ホスト", value=SD_HOST)
                        input_sd_port = gr.Textbox(label="ポート番号", value=SD_PORT)
                    with gr.Row():
                        input_webui_path = gr.Textbox(label="インストールフォルダ", value=SD_WEBUI_PATH)
                    with gr.Row():
                        input_boot_args = gr.Textbox(label="追加起動オプション", value=SD_BOOT_ARGS, placeholder="--xformers --no-half-vae")
                    with gr.Row():
                        input_output_dir = gr.Textbox(label="画像の保存先", value=BASE_OUTPUT_DIR, interactive=True, placeholder="パスを入力してください...")
                        
                    save_msg = gr.Markdown("")
                    with gr.Row():
                        btn_save_settings = gr.Button("💾 保存", variant="primary")
                        btn_cancel_settings = gr.Button("キャンセル", variant="secondary")
                    btn_reset_settings = gr.Button("↩️ 設定をリセット", variant="stop")

        with gr.Group(visible=False) as modal_stop_confirm:
            with gr.Group(elem_classes="modal-container"):
                with gr.Column(elem_classes="modal-content"):
                    gr.Markdown("### ⚠️ 画像生成を中止しますか？")
                    gr.Markdown("現在実行中の処理を中止します。")
                    with gr.Row():
                        btn_stop_yes = gr.Button("はい、します", variant="stop")
                        btn_stop_no = gr.Button("いいえ、続けます", variant="secondary")

        state_gen_images = gr.State([])
        state_original_image = gr.State()
        state_view_mode = gr.State(value="生成画")

        state_params_tab1 = gr.State([])
        state_params_tab2 = gr.State([])

        state_selected_index_1 = gr.State(0)   
        state_selected_index_2 = gr.State(0)
        
        with gr.Group(visible=False) as modal_wrapper_1:
            with gr.Group(elem_classes="modal-container"):
                with gr.Column(elem_classes="modal-content"):
                    gr.Markdown("### 📝 生成パラメータ（PNG info）")
                    output_info_1 = gr.Textbox(label="", lines=10, interactive=False, show_copy_button=True, container=False)
                    btn_close_modal_1 = gr.Button("閉じる", variant="secondary")
        
        with gr.Tabs():
            # Tab1
            with gr.Tab("ラフ画チェック"):
                gr.Markdown("""
                ### 🖌️ ラフ画を元に、AIが修正案を提案します。
                """)
                input_hint = gr.Textbox(label="AIへのヒント（prompt）", placeholder="赤いショートヘア、決意の表情、剣を構える、光る刀身、なびくマント、土埃...")
                with gr.Row(equal_height=False):
                    with gr.Column(scale=3, min_width=400):
                        input_img = gr.Image(label="ラフ画をドロップ", type="filepath", elem_id="input_img")
                        with gr.Group():
                            slider_batch = gr.Slider(minimum=1, maximum=10, step=1, value=1, label="生成枚数（Batch count）")
                            with gr.Row(elem_classes="settings-row"):
                                radio_strength = gr.Radio(choices=["弱", "中", "強"], value="中", label="変更度合い（Denoising strength）", interactive=True)
                            radio_ad = gr.Radio(choices=["なし", "顔のみ", "手のみ", "顔と手"], value="なし", label="顔と手の補正 (ADetailer)")
                            input_seed = gr.Number(label="乱数（Seed）", value=-1, precision=0)
                    
                    with gr.Column(scale=1, min_width=100, elem_classes="control-panel"):
                        btn_cleanup = gr.Button("実行 ➡", variant="primary", elem_id="btn_cleanup")
                        btn_stop_trigger = gr.Button("■ 中止", variant="stop", elem_id="btn_stop", visible=False)
                    
                    with gr.Column(scale=5, min_width=400):
                        with gr.Group(elem_id="output_image_wrapper"):
                            output_cleanup = gr.Gallery(label="AIからの提案", interactive=False, elem_id="output_img", columns=1, object_fit="contain", format="png", visible=True, preview=True)
                            btn_info_1 = gr.Button("ℹ️", elem_id="info_btn", visible=False)
                            
                        with gr.Row(elem_classes="footer-btn-row"):
                            btn_toggle_diff = gr.Button("🔄 元画像と切替", size="sm")
                            btn_open_folder = gr.Button("📂 保存先を開く", size="sm")
                
                gen_event = btn_cleanup.click(fn=reset_ui_state, inputs=None, outputs=btn_cleanup).then(
                    fn=cleanup_sketch, 
                    inputs=[input_img, input_hint, slider_batch, radio_strength, radio_ad, input_seed],
                    outputs=[state_gen_images, state_params_tab1, btn_info_1, state_original_image, btn_cleanup]
                ).then(
                    fn=lambda imgs: gr.update(value=imgs, columns=1, visible=True), 
                    inputs=state_gen_images,
                    outputs=output_cleanup
                )

                output_cleanup.select(fn=on_gallery_select, inputs=None, outputs=state_selected_index_1)
                
                btn_stop_trigger.click(lambda: gr.update(visible=True), None, modal_stop_confirm)
                
                btn_toggle_diff.click(fn=toggle_view, inputs=[state_view_mode, state_gen_images, state_original_image], outputs=[output_cleanup, state_view_mode], show_progress="hidden").then(lambda mode: f"🎨 生成画を表示" if mode == "元画像" else "🔄 元画像と切替", state_view_mode, btn_toggle_diff)
                
                btn_info_1.click(
                    fn=get_selected_param, 
                    inputs=[state_params_tab1, state_selected_index_1], 
                    outputs=output_info_1
                ).then(lambda: gr.update(visible=True), None, modal_wrapper_1)

                btn_close_modal_1.click(lambda: gr.update(visible=False), None, modal_wrapper_1)
                btn_open_folder.click(fn=open_output_folder)

            # Tab2
            with gr.Tab("顔チェック"):
                gr.Markdown("""
                ### ✨ 顔を自動検出し、AIが修正案を提案します。
                """)
                input_hint_face = gr.Textbox(label="AIへのヒント（prompt）", placeholder="ピンクの瞳、驚きの表情、赤面、汗...")
                with gr.Row(equal_height=False):
                    with gr.Column(scale=3, min_width=400):
                        input_img_face = gr.Image(label="画像をドロップ", type="filepath")
                        with gr.Group():
                            slider_batch_face = gr.Slider(minimum=1, maximum=10, step=1, value=1, label="生成枚数（Batch count）")
                            with gr.Row(elem_classes="settings-row"):
                                radio_strength_face = gr.Radio(choices=["弱", "中", "強"], value="中", label="変更度合い（ADetailer inpaint denoising strength）", interactive=True)
                            input_seed = gr.Number(label="乱数（Seed）", value=-1, precision=0)
                    
                    with gr.Column(scale=1, min_width=100, elem_classes="control-panel"):
                        btn_face_fix = gr.Button("実行 ➡", variant="primary", elem_id="btn_face_fix")
                        btn_stop_trigger_face = gr.Button("■ 中止", variant="stop", elem_id="btn_stop_face", visible=False)
                    
                    with gr.Column(scale=5, min_width=400):                        
                        with gr.Group(elem_id="output_image_wrapper"):
                            output_face = gr.Gallery(label="AIからの提案", interactive=False, elem_id="output_face_gallery", columns=1, object_fit="contain", format="png", visible=True, preview=True)
                            btn_info_face = gr.Button("ℹ️", elem_id="info_btn_2", visible=False)
                            
                        with gr.Row(elem_classes="footer-btn-row"):
                            btn_toggle_diff_face = gr.Button("🔄 元画像と切替", size="sm")
                            btn_open_folder_face = gr.Button("📂 保存先を開く", size="sm")

                btn_face_fix.click(fn=reset_ui_state, inputs=None, outputs=btn_face_fix).then(
                    fn=fix_face_only,
                    inputs=[input_img_face, input_hint_face, slider_batch_face, radio_strength_face, input_seed],
                    outputs=[state_gen_images, state_params_tab2, btn_info_face, state_original_image, btn_face_fix]
                ).then(
                    fn=lambda imgs: gr.update(value=imgs, columns=1, visible=True),
                    inputs=state_gen_images,
                    outputs=output_face
                )

                output_face.select(fn=on_gallery_select, inputs=None, outputs=state_selected_index_2)

                btn_stop_trigger_face.click(lambda: gr.update(visible=True), None, modal_stop_confirm)
                
                btn_toggle_diff_face.click(
                    fn=toggle_view,
                    inputs=[state_view_mode, state_gen_images, state_original_image],
                    outputs=[output_face, state_view_mode],
                    show_progress="hidden"
                ).then(lambda mode: f"🎨 生成画を表示" if mode == "元画像" else "🔄 元画像と切替", state_view_mode, btn_toggle_diff_face)

                btn_info_face.click(
                    fn=get_selected_param,
                    inputs=[state_params_tab2, state_selected_index_2],
                    outputs=output_info_1
                ).then(lambda: gr.update(visible=True), None, modal_wrapper_1)
                
                btn_open_folder_face.click(fn=open_output_folder)

        # 共通
        btn_stop_yes.click(fn=interrupt_generation, outputs=None).then(lambda: gr.update(visible=False), None, modal_stop_confirm)
        btn_stop_no.click(lambda: gr.update(visible=False), None, modal_stop_confirm)
        
        btn_settings.click(fn=refresh_settings_ui, outputs=[input_sd_host, input_sd_port, input_webui_path, input_boot_args, input_output_dir]).then(lambda: gr.update(visible=True), None, modal_settings)
        btn_cancel_settings.click(lambda: gr.update(visible=False), None, modal_settings)
        btn_save_settings.click(fn=save_settings_to_file, inputs=[input_sd_host, input_sd_port, input_webui_path, input_boot_args, input_output_dir], outputs=[save_msg]).then(lambda: gr.update(visible=False), None, modal_settings)
        btn_reset_settings.click(fn=reset_settings_ui, outputs=[input_sd_host, input_sd_port, input_webui_path, input_boot_args, input_output_dir]).then(lambda: "", None, save_msg)

        style_default = gr.HTML(visible=False)
        timer = gr.Timer(3.0)
        
        poll_outputs = [
            status_display, sd_url_display, logs_display, btn_start_server, 
            btn_cleanup, btn_stop_trigger, 
            btn_face_fix, btn_stop_trigger_face, 
            style_default
        ]
        
        timer.tick(fn=poll_status, outputs=poll_outputs)
        btn_start_server.click(fn=start_sd_server, outputs=poll_outputs)
        btn_refresh.click(fn=poll_status, outputs=poll_outputs)

    if __name__ == "__main__":
        print("🚀 アプリを起動中...")
        demo.launch(server_port=APP_PORT, inbrowser=True, server_name="127.0.0.1")

except Exception as e:
    print("\n" + "="*60)
    print("❌ 予期せぬエラーが発生しました。")
    print(traceback.format_exc())
    print("="*60 + "\n")
    wait_before_exit()