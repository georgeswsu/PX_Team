import cv2
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient
import mysql.connector
import pandas as pd
import requests
import re

# Configure Azure Custom Vision
cv_endpoint = "https://pxtest0-prediction.cognitiveservices.azure.com/customvision/v3.0/Prediction"
cv_prediction_key = "f313aaf51e244d73a2ca583ca643d7b4"
cv_project_id = "350730f2-0e23-4adf-a6a8-f8b416a7bd1d"
cv_model_name = "PXtest-v1"

# Configure Azure Form Recognizer
form_recognizer_endpoint = "https://pxtest8.cognitiveservices.azure.com/"
form_recognizer_key = "a130c75f646741ba90d5b40a8aa1fa5b"

# Configure MySQL
mysql_host = "localhost"
mysql_user = "root"
mysql_password = "85982480hy"
mysql_database = "pxtest"

image_path = "data/R.jpg"


# Detect rooms using Custom Vision
def detect_rooms(image_path):
    request_url = f"{cv_endpoint}/{cv_project_id}/detect/iterations/{cv_model_name}/image"
    headers = {
        "Prediction-Key": cv_prediction_key,
        "Content-Type": "application/octet-stream"
    }
    with open(image_path, "rb") as image_data:
        response = requests.post(request_url, headers=headers, data=image_data)
        if response.status_code == 200:
            result = response.json()
            print("Detected Rooms:", result['predictions'])
            return result['predictions']
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")

def analyze_floor_plan(image_path):
    client = DocumentAnalysisClient(form_recognizer_endpoint, AzureKeyCredential(form_recognizer_key))
    extracted_rooms = {'roomname': [], 'size': []}

    with open(image_path, "rb") as image:
        poller = client.begin_analyze_document("prebuilt-layout", image)
        result = poller.result()

    room_keywords = ['bedroom', 'kitchen', 'bathroom', 'living room', 'dining room', 'hall', 'office', 'study',
                     'laundry', 'garage']

    size_pattern = r"\d+(\.\d+)?['′]?\d*['″]?\s*[x×]\s*\d+(\.\d+)?['′]?\d*['″]?"

    for page in result.pages:
        for line in page.lines:
            content_lower = line.content.lower()
            if line.content:
                if any(keyword in content_lower for keyword in room_keywords):
                    extracted_rooms['roomname'].append({
                        "content": line.content,
                        "bounding_box": convert_polygon_to_bbox(line.polygon)
                    })
                elif re.match(size_pattern, line.content):
                    extracted_rooms['size'].append({
                        "content": line.content,
                        "bounding_box": convert_polygon_to_bbox(line.polygon)
                    })

    #print("Extracted Rooms:", extracted_rooms)
    return extracted_rooms


# Match detected rooms with extracted names and sizes
def match_rooms(detected_rooms, extracted_rooms, image_width, image_height):
    matched_rooms = []

    for detected_room in detected_rooms:
        if detected_room['tagName'] == 'namedroom':
            bounding_box = convert_to_pixels(detected_room['boundingBox'], image_width, image_height)
            room_name = "N/A"
            room_size = "N/A"

            #print(f"Processing detected room with bounding box: {bounding_box}")

            for name_entry in extracted_rooms['roomname']:
                #print(f"Checking name entry: {name_entry}")
                if is_within(bounding_box, name_entry['bounding_box']):
                    room_name = name_entry['content']
                    break

            for size_entry in extracted_rooms['size']:
                #print(f"Checking size entry: {size_entry}")
                if is_within(bounding_box, size_entry['bounding_box']):
                    room_size = parse_room_size(size_entry['content'])
                    break

            matched_rooms.append({
                "room_tag": detected_room['tagName'],
                "room_name": room_name,
                "room_size": room_size
            })

    #print("Matched Rooms:", matched_rooms)
    return matched_rooms

def convert_polygon_to_bbox(polygon):
    """Convert a polygon to a bounding box (left, top, right, bottom)."""
    x_coords = [point.x for point in polygon]
    y_coords = [point.y for point in polygon]
    return {
        'left': min(x_coords),
        'top': min(y_coords),
        'right': max(x_coords),
        'bottom': max(y_coords)
    }

def convert_to_pixels(bounding_box, image_width, image_height):
    """Convert bounding box from percentage to pixel coordinates."""
    return {
        'left': bounding_box['left'] * image_width,
        'top': bounding_box['top'] * image_height,
        'right': (bounding_box['left'] + bounding_box['width']) * image_width,
        'bottom': (bounding_box['top'] + bounding_box['height']) * image_height
    }

def is_within(box1, box2):
    """Check if box1 is within box2."""
    return (box1['left'] < box2['right'] and box1['right'] > box2['left'] and
            box1['top'] < box2['bottom'] and box1['bottom'] > box2['top'])

def parse_room_size(text):
    patterns = [
        r'(\d+)\s*x\s*(\d+)',
        r'(\d+)\s*\'\s*(\d+)\s*\"',
        r'(\d+)\s*\'\s*(\d+)\s*\'\'',
        r'(\d+)\s*\'\s*(\d+)\s*\"'
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            width, height = match.groups()
            width, height = convert_to_inches(width, height)
            return f"{width} x {height} inches"

    return text

def convert_to_inches(width, height):
    def to_inches(val):
        if '\'' in val:
            feet, inches = val.split('\'')
            return int(feet) * 12 + int(inches.replace('\"', ''))
        else:
            return int(val)

    return to_inches(width), to_inches(height)

def get_image_size(image_path):
    """Get the width and height of the image."""
    image = cv2.imread(image_path)
    height, width, _ = image.shape
    return width, height

def filter_detected_rooms_by_probability(detected_rooms, threshold=0.5):

    filtered_rooms = [room for room in detected_rooms if room.get('probability', 0) > threshold]
    return filtered_rooms

# Store results into MySQL
def store_to_mysql(matched_rooms):
    connection = mysql.connector.connect(
        host=mysql_host,
        user=mysql_user,
        password=mysql_password,
        database=mysql_database
    )

    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            id INT AUTO_INCREMENT PRIMARY KEY,
            room_tag VARCHAR(255),
            room_name VARCHAR(255),
            room_size VARCHAR(255)
        )
    """)

    for room in matched_rooms:
        cursor.execute("""
            INSERT INTO rooms (room_tag, room_name, room_size) VALUES (%s, %s, %s)
        """, (room["room_tag"], room["room_name"], room["room_size"]))

    connection.commit()
    cursor.close()
    connection.close()


# Generate Excel report
def generate_excel(matched_rooms):
    df = pd.DataFrame(matched_rooms)
    df.to_excel("matched_rooms.xlsx", index=False)



# Main execution
if __name__ == "__main__":

    image_width, image_height = get_image_size(image_path)
    detected_rooms = filter_detected_rooms_by_probability(detect_rooms(image_path))
    extracted_rooms = analyze_floor_plan(image_path)
    matched_rooms = match_rooms(detected_rooms, extracted_rooms, image_width, image_height)
    store_to_mysql(matched_rooms)
    generate_excel(matched_rooms)
    print("Finished!")
