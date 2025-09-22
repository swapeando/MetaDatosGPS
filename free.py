from io import BytesIO
from flask import Flask, request, send_file, render_template_string
from PIL import Image, ImageChops
import piexif
import requests
import base64
import os
import threading
import webbrowser
import time
import sys

app = Flask(__name__)

# ------------------- Utilities -------------------

def download_image(url, timeout=15):
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return BytesIO(resp.content)


def extract_exif_full(image_bytes_io):
    image_bytes_io.seek(0)
    exif_data = {}
    try:
        data = image_bytes_io.getvalue()
        exif_dict = piexif.load(data)
        for ifd in exif_dict:
            if ifd == 'thumbnail':
                continue
            exif_data[ifd] = {}
            for tag, val in exif_dict[ifd].items():
                try:
                    name = piexif.TAGS[ifd][tag]['name']
                except KeyError:
                    name = str(tag)
                if isinstance(val, bytes):
                    try:
                        val = val.decode(errors='ignore')
                    except:
                        val = repr(val)
                exif_data[ifd][name] = val
        # Extract GPS coordinates if present
        gps = exif_dict.get('GPS', {})
        gps_coords = None
        if gps:
            def dms_to_deg(dms, ref):
                deg = dms[0][0] / dms[0][1]
                min = dms[1][0] / dms[1][1]
                sec = dms[2][0] / dms[2][1]
                val = deg + min/60 + sec/3600
                if ref in ['S', 'W']:
                    val = -val
                return val
            try:
                lat = dms_to_deg(gps[2], gps[1].decode())
                lon = dms_to_deg(gps[4], gps[3].decode())
                gps_coords = (lat, lon)
            except Exception:
                gps_coords = None
        exif_data['GPS_Coordinates'] = gps_coords
    except Exception as e:
        exif_data['error'] = str(e)
    return exif_data


def generate_ela(image_bytes_io, quality=90):
    image_bytes_io.seek(0)
    orig = Image.open(image_bytes_io).convert('RGB')
    buf = BytesIO()
    orig.save(buf, 'JPEG', quality=quality)
    buf.seek(0)
    recompressed = Image.open(buf).convert('RGB')
    ela = ImageChops.difference(orig, recompressed)
    extrema = ela.getextrema()
    max_diff = max([e[1] for e in extrema]) if extrema else 1
    factor = 1 if max_diff == 0 else 255.0 / max_diff
    ela = Image.eval(ela, lambda px: int(px * factor))
    out = BytesIO()
    ela.save(out, format='PNG')
    out.seek(0)
    return out

# ------------------- HTML Template (Neon style) -------------------

HTML_PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>API Made by AndoIlegal</title>
<style>
    html,body{height:100%;margin:0}
    body{background:#000;color:#fff;font-family:Arial,Helvetica,sans-serif;display:flex;align-items:center;justify-content:center}
    .container{width:90%;max-width:900px;text-align:center;background:rgba(0,0,0,0.6);padding:30px;border-radius:12px;position:relative;z-index:2}
    h1{font-size:36px;margin:0 0 10px 0;color:#ff2d2d;text-shadow:0 0 8px rgba(255,45,45,0.9),0 0 20px rgba(255,45,45,0.6);animation:glow 2s ease-in-out infinite}
    @keyframes glow{0%{text-shadow:0 0 6px rgba(255,45,45,0.6)}50%{text-shadow:0 0 20px rgba(255,45,45,1)}100%{text-shadow:0 0 6px rgba(255,45,45,0.6)}}
    form{margin:18px 0}
    input[type=text]{width:70%;padding:8px;border-radius:6px;border:1px solid #222;background:#111;color:#fff}
    input[type=file]{color:#fff}
    input[type=submit]{padding:8px 14px;border-radius:6px;border:none;background:#ff2d2d;color:#fff;cursor:pointer}
    pre{text-align:left;background:#010101;padding:12px;border-radius:8px;overflow:auto}
    /* neon side lines */
    .neon-line{position:fixed;top:0;bottom:0;width:8px;background:linear-gradient(180deg,transparent,rgba(255,255,255,0.08),transparent);left:0;animation:slide1 3s linear infinite}
    .neon-line.right{right:0;left:auto;animation:slide2 3s linear infinite}
    @keyframes slide1{0%{box-shadow:0 0 2px 0 rgba(255,255,255,0.02)}50%{box-shadow:0 0 20px 2px rgba(255,255,255,0.08)}100%{box-shadow:0 0 2px 0 rgba(255,255,255,0.02)}}
    @keyframes slide2{0%{box-shadow:0 0 2px 0 rgba(255,255,255,0.02)}50%{box-shadow:0 0 20px 2px rgba(255,255,255,0.08)}100%{box-shadow:0 0 2px 0 rgba(255,255,255,0.02)}}
    img.ela{max-width:100%;height:auto;border:1px solid rgba(255,255,255,0.06);margin-top:12px}
</style>
</head>
<body>
<div class="neon-line"></div>
<div class="neon-line right"></div>
<div class="container">
  <h1>API Made by AndoIlegal</h1>
  <p style="color:#aaa">Simple forensic look — URL or upload</p>
  <h2 style="color:#fff">Analyze by URL</h2>
  <form method="POST" action="/analyze_url_web">
      <input type="text" name="url" placeholder="https://example.com/image.jpg">
      <input type="submit" value="Analyze">
  </form>
  <h2 style="color:#fff">Analyze by File</h2>
  <form method="POST" action="/analyze_upload_web" enctype="multipart/form-data">
      <input type="file" name="file">
      <input type="submit" value="Analyze">
  </form>
  {% if image_info %}
  <h3 style="color:#ddd">Image info</h3>
  <ul style="text-align:left;display:inline-block;max-width:820px">
    {% for key,val in image_info.items() %}
      <li><strong>{{key}}:</strong> {{val}}</li>
    {% endfor %}
  </ul>
  {% endif %}
  {% if exif %}
  <h3 style="color:#ddd">EXIF</h3>
  <pre>{{ exif }}</pre>
  {% endif %}
  {% if ela_image %}
  <h3 style="color:#ddd">ELA Result</h3>
  <img class="ela" src="data:image/png;base64,{{ ela_image }}">
  {% endif %}
</div>
</body>
</html>
"""

# ------------------- Flask Web Endpoints -------------------

@app.route('/')
def home():
    return render_template_string(HTML_PAGE)

@app.route('/analyze_url_web', methods=['POST'])
def analyze_url_web():
    url = request.form.get('url')
    if not url:
        return "URL empty", 400
    try:
        img_io = download_image(url)
        img_io.seek(0)
        image = Image.open(img_io)
        image_info = {
            'Format': image.format,
            'Size': image.size,
            'Mode': image.mode,
            'Source': url
        }
        exif = extract_exif_full(img_io)
        # If no GPS, show message
        if exif.get('GPS_Coordinates') is None:
            exif['GPS_Coordinates'] = 'No location available (metadata removed or not present)'
        ela_io = generate_ela(img_io)
        ela_b64 = base64.b64encode(ela_io.getvalue()).decode('ascii')
        return render_template_string(HTML_PAGE, image_info=image_info, exif=exif, ela_image=ela_b64)
    except Exception as e:
        return f"Error: {e}"

@app.route('/analyze_upload_web', methods=['POST'])
def analyze_upload_web():
    if 'file' not in request.files:
        return "No file uploaded", 400
    f = request.files['file']
    img_io = BytesIO(f.read())
    img_io.seek(0)
    image = Image.open(img_io)
    image_info = {
        'Filename': f.filename,
        'Format': image.format,
        'Size': image.size,
        'Mode': image.mode
    }
    exif = extract_exif_full(img_io)
    if exif.get('GPS_Coordinates') is None:
        exif['GPS_Coordinates'] = 'No location available (metadata removed or not present)'
    ela_io = generate_ela(img_io)
    ela_b64 = base64.b64encode(ela_io.getvalue()).decode('ascii')
    return render_template_string(HTML_PAGE, image_info=image_info, exif=exif, ela_image=ela_b64)

# ------------------- API Endpoints (JSON / CURL) -------------------

@app.route('/analyze_url', methods=['POST'])
def analyze_url():
    data = request.get_json(force=True)
    if not data or 'url' not in data:
        return {'error': 'missing url in JSON body'}, 400
    url = data['url']
    try:
        img_io = download_image(url)
        img_io.seek(0)
        image = Image.open(img_io)
        image_info = {
            'Format': image.format,
            'Size': image.size,
            'Mode': image.mode,
            'Source': url
        }
        exif = extract_exif_full(img_io)
        if exif.get('GPS_Coordinates') is None:
            exif['GPS_Coordinates'] = 'No location available (metadata removed or not present)'
        ela_io = generate_ela(img_io)
        ela_b64 = base64.b64encode(ela_io.getvalue()).decode('ascii')
        return {'image_info': image_info, 'exif': exif, 'ela_png_base64': ela_b64}
    except Exception as e:
        return {'error': str(e)}, 500

@app.route('/analyze_upload', methods=['POST'])
def analyze_upload():
    if 'file' not in request.files:
        return {'error': 'no file uploaded'}, 400
    f = request.files['file']
    img_io = BytesIO(f.read())
    img_io.seek(0)
    image = Image.open(img_io)
    image_info = {
        'Filename': f.filename,
        'Format': image.format,
        'Size': image.size,
        'Mode': image.mode
    }
    exif = extract_exif_full(img_io)
    if exif.get('GPS_Coordinates') is None:
        exif['GPS_Coordinates'] = 'No location available (metadata removed or not present)'
    ela_io = generate_ela(img_io)
    ela_io.seek(0)
    return send_file(ela_io, mimetype='image/png', as_attachment=False, download_name='ela.png')

# ------------------- Console UI + server runner -------------------

def run_server():
    # Run Flask without reloader so thread stays stable
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)


def process_url_console(url):
    try:
        print('\nProcessing URL:', url)
        img_io = download_image(url)
        img_io.seek(0)
        image = Image.open(img_io)
        exif = extract_exif_full(img_io)
        if exif.get('GPS_Coordinates') is None:
            exif['GPS_Coordinates'] = 'No location available (metadata removed or not present)'
        ela_io = generate_ela(img_io)
        out_path = os.path.join(os.getcwd(), 'ela_console.png')
        with open(out_path, 'wb') as f:
            f.write(ela_io.getvalue())
        print('Saved ELA to', out_path)
        print('Image info:')
        print(' - Format:', image.format)
        print(' - Size:', image.size)
        print(' - Mode:', image.mode)
        print('EXIF (summary):')
        for k,v in exif.items():
            print(' -', k, ':', v)
    except Exception as e:
        print('Error processing URL:', e)


def process_file_console(path):
    try:
        print('\nProcessing file:', path)
        with open(path, 'rb') as fh:
            data = fh.read()
        img_io = BytesIO(data)
        img_io.seek(0)
        image = Image.open(img_io)
        exif = extract_exif_full(img_io)
        if exif.get('GPS_Coordinates') is None:
            exif['GPS_Coordinates'] = 'No location available (metadata removed or not present)'
        ela_io = generate_ela(img_io)
        out_path = os.path.join(os.getcwd(), 'ela_console.png')
        with open(out_path, 'wb') as f:
            f.write(ela_io.getvalue())
        print('Saved ELA to', out_path)
        print('Image info:')
        print(' - Filename:', os.path.basename(path))
        print(' - Format:', image.format)
        print(' - Size:', image.size)
        print(' - Mode:', image.mode)
        print('EXIF (summary):')
        for k,v in exif.items():
            print(' -', k, ':', v)
    except Exception as e:
        print('Error processing file:', e)


def console_menu():
    print('ON')
    print('API Made by AndoIlegal')
    print()
    while True:
        print('\nChoose an option:')
        print('1] Analyze by Link (enter an image URL)')
        print('2] Analyze by File (enter a local file path)')
        print('3] Open Web UI (upload from browser)')
        print('4] Quit')
        choice = input('> ').strip()
        if choice == '1':
            url = input('Enter image URL: ').strip()
            if url:
                process_url_console(url)
        elif choice == '2':
            path = input('Enter path to image file: ').strip()
            if path:
                process_file_console(path)
        elif choice == '3':
            print('Opening web UI at http://127.0.0.1:5000/')
            webbrowser.open('http://127.0.0.1:5000/')
        elif choice == '4':
            print('Exiting...')
            os._exit(0)
        else:
            print('Invalid option')


if __name__ == '__main__':
    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    # Wait a moment for server to bind
    time.sleep(0.8)
    try:
        console_menu()
    except (KeyboardInterrupt, EOFError):
        print('\nShutting down...')
        sys.exit(0)