import json

def check(file_path):
    print(f"Checking {file_path}...")
    with open(file_path, 'rb') as f:
        content = f.read()

    boms = {
        'UTF-8': b'\xef\xbb\xbf',
        'UTF-16 LE': b'\xff\xfe',
        'UTF-16 BE': b'\xfe\xff',
        'UTF-32 LE': b'\xff\xfe\x00\x00',
        'UTF-32 BE': b'\x00\x00\xfe\xff',
    }
    has_bom = False
    for name, bom in boms.items():
        if content.startswith(bom):
            print(f"FAIL: {file_path} contains a {name} BOM!")
            has_bom = True
            break
    if not has_bom:
        print(f"PASS: {file_path} BOM checking")
        try:
            data = json.loads(content.decode('utf-8'))
            print(f"PASS: {file_path} JSON integrity. Entries: {len(data)}")
        except Exception as e:
            print(f"FAIL: {file_path} JSON integrity: {e}")
            
check('static/faq_cache.json')
check('static/greeting_cache.json')
