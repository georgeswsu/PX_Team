from flask import Flask, request, jsonify, render_template
import os
import mysql.connector
from main import detect_rooms, analyze_floor_plan, match_rooms, get_image_size, store_to_mysql, \
    filter_detected_rooms_by_probability

app = Flask(__name__)

# MySQL configuration
mysql_host = "localhost"
mysql_user = "root"
mysql_password = "85982480hy"
mysql_database = "pxtest"

# Upload folder
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Database connection function
def create_db_connection():
    return mysql.connector.connect(
        host=mysql_host,
        user=mysql_user,
        password=mysql_password,
        database=mysql_database
    )

# Route for rendering the HTML upload page
@app.route('/')
def index():
    return render_template('index.html')

# Route for uploading and analyzing images
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No files in the request'}), 400

    files = request.files.getlist('file')
    area_names = request.form.getlist('areaNames[]')  # Ensure the correct key for area names

    # Debugging: Print received data
    print("Files received:", [file.filename for file in files])
    print("Area names received:", area_names)

    if not files:
        return jsonify({'error': 'No files in the request'}), 400

    if len(files) != len(area_names):
        # If the number of area names does not match the number of files, use filenames as area names
        area_names = [file.filename for file in files]
        if len(files) != len(area_names):
            return jsonify({'error': 'Mismatch between number of files and area names'}), 400

    results = []

    for file, area in zip(files, area_names):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)

        # Analyze the uploaded image using program2
        image_width, image_height = get_image_size(file_path)
        detected_rooms = filter_detected_rooms_by_probability(detect_rooms(file_path))
        extracted_rooms = analyze_floor_plan(file_path)
        matched_rooms = match_rooms(detected_rooms, extracted_rooms, image_width, image_height)

        # Modify matched_rooms to include area names
        for room in matched_rooms:
            room['room_tag'] = area

        # Store the results to MySQL
        store_to_mysql(matched_rooms)

        results.append({'filename': file.filename, 'area': area, 'matched_rooms': matched_rooms})

    return jsonify({'results': results})



# Run the app
if __name__ == '__main__':
    app.run(debug=True)
