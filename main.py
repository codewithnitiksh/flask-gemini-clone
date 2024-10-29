from flask import Flask, render_template, redirect, url_for, jsonify, request, Response
import os
import google.generativeai as genai
from werkzeug.utils import secure_filename
from PIL import Image
import io
from flask import Flask, request, jsonify, make_response
import firebase_admin
from firebase_admin import credentials, auth, db, storage
import json
from datetime import datetime, timezone

# Load the service account key JSON file
cred = credentials.Certificate('./serviceAccountKey.json')

# Initialize the Firebase Admin SDK
firebase_admin.initialize_app(cred, {
    'databaseURL': "https://chatter-13894-default-rtdb.firebaseio.com",
    'storageBucket': "chatter-13894.appspot.com"
})


app = Flask(__name__)


@app.route("/")
def home():
    # Get uid from cookies
    uid = request.cookies.get('uid')

    if not uid:
        # Redirect to login page if no uid is found
        return redirect(url_for('login'))

    try:
        # Verify the uid with Firebase Authentication
        user = auth.get_user(uid)
    except Exception as e:
        # If user is not found or there's an error, redirect to login page
        # # print(f"Authentication failed: {str(e)}")
        return redirect(url_for('login'))

    # Check if the user entry exists in the Realtime Database
    user_ref = db.reference(f'users/{uid}')
    snapshot = user_ref.get()

    if snapshot is None:
        # If no entry exists, create a new entry
        user_ref.set({
            'createdAt': datetime.now().isoformat(),
            # Add additional user information if needed
        })
        # print(f"New user created in the database: {uid}")

    # Render the home page
    return render_template("index.html")


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/check_connection")
def check_connection():
    # Initialize response message
    response = {
        'database': 'Not connected',
        'storage': 'Not connected'
    }

    # Check Realtime Database connection
    try:
        # Attempt to read a dummy reference from the database
        ref = db.reference('/test_connection')
        ref.get()  # This will raise an exception if the connection fails
        response['database'] = 'Connected'
    except Exception as e:
        response['database'] = f'Failed to connect: {str(e)}'

    # Check Firebase Storage connection
    try:
        # Attempt to list files from a dummy path in storage
        bucket = storage.bucket()
        # List blobs to check connection
        blobs = bucket.list_blobs(max_results=1)
        response['storage'] = 'Connected'
    except Exception as e:
        response['storage'] = f'Failed to connect: {str(e)}'

    return jsonify(response)


@app.route('/createNewChat', methods=['POST'])
def create_new_chat():
    try:
        # Get JSON data from the request
        data = request.get_json()
        text = data.get('text')

        # Extract the UID from the cookies
        uid = request.cookies.get('uid')

        if text and uid:
            # Get a reference to the Firebase Realtime Database
            ref = db.reference(f'users/{uid}/chats')

            # Check if the chat name already exists
            existing_chat = ref.child(text).get()
            if existing_chat:
                return jsonify({'message': 'Chat already exists. Choose another one.'}), 400

            # Add the new chat message with the text as the key
            ref.child(text).set({
                # Save current timestamp
                'createdAt': datetime.now(timezone.utc).isoformat()
            })

            return jsonify({'message': 'Chat message added successfully.'}), 200
        else:
            return jsonify({'message': 'No text provided or user not authenticated.'}), 400
    except Exception as e:
        # print(f'Error: {str(e)}')
        return jsonify({'message': 'An error occurred.'}), 500


@app.route('/getChats', methods=['GET'])
def get_chats():
    uid = request.cookies.get('uid')
    if not uid:
        return jsonify({'message': 'User not authenticated.'}), 401

    try:
        # Fetch chat names from the database
        chats_ref = db.reference(f'users/{uid}/chats')
        chats_snapshot = chats_ref.get()
        if not chats_snapshot:
            return jsonify({'chats': []}), 200

        # Extract chat names
        chat_names = list(chats_snapshot.keys())
        return jsonify({'chats': chat_names}), 200
    except Exception as e:
        # print(f"Error fetching chats: {str(e)}")
        return jsonify({'message': 'An error occurred while fetching chats.'}), 500


# Set the Google API key
GOOGLE_API_KEY = "AIzaSyCi4nRDQy-7ipqzhP1Em_BOcJfxyx1hnw0"

# Configure the API key
genai.configure(api_key=GOOGLE_API_KEY)

# Initialize the model
model = genai.GenerativeModel("gemini-1.5-flash")

# Start a chat session with some initial history
'''
chat = model.start_chat(
    history=[
        {"role": "user", "parts": "Hello"},
        {"role": "model", "parts": "Great to meet you. What would you like to know?"},
    ]
)
'''


@app.route('/getChatHistory', methods=['POST'])
def get_chat_history():
    global chat  # Declare 'chat' as global at the start of the function
    try:
        # Get JSON data from the request
        data = request.get_json()
        chat_name = data.get('chatName')

        if not chat_name:
            return jsonify({'message': 'Chat name not provided.'}), 400

        # Extract UID from cookies
        uid = request.cookies.get('uid')
        if not uid:
            return jsonify({'message': 'User not authenticated.'}), 401

        # Query the Firebase database for chat history
        chat_ref = db.reference(f'users/{uid}/chats/{chat_name}/history')
        chat_history = chat_ref.get()

        if chat_history:
            # Convert chat history to the required format
            formatted_history = [
                {"role": "user", "parts": entry['user_message']} if i % 2 == 0
                else {"role": "model", "parts": entry['response_message']}
                for i, (key, entry) in enumerate(chat_history.items())
            ]

            # # print chat history to the terminal
            # print(f"Chat history for {chat_name}: {formatted_history}")

            # Start a chat session with the formatted history
            chat = model.start_chat(history=formatted_history)

            # Return the chat history to the client
            return jsonify({'message': 'Success', 'history': chat_history}), 200
        else:
            # Set the chat model with the default history
            default_history = []

            # Start a chat session with the default history
            chat = model.start_chat(history=default_history)

            # # print the default history to the terminal
            # print(f"No chat history found for {chat_name}. Using default history: {default_history}")

            # Return the default history to the client
            return jsonify({'message': 'No chat history found. Using default history.', 'history': default_history}), 404
    except Exception as e:
        # print(f"Error fetching chat history: {str(e)}")
        return jsonify({'message': 'An error occurred.'}), 500


@app.route("/api", methods=["POST"])
def qa():
    try:
        # Ensure the temp directory exists
        if not os.path.exists('temp'):
            os.makedirs('temp')

        # Get text from the form data
        text = request.form.get('text', '')
        if not text:
            return jsonify({"result": "No text provided in the request."}), 400

        # Check if a file is included in the request
        file = request.files.get('file')  # For images
        audioFile = request.files.get('audioFile')  # For audio
        selectedChatName = request.form.get(
            'selectedChatName')  # For chat name
        # print("selectedChatName - > ", selectedChatName)
        if not selectedChatName or selectedChatName == "None":
            return jsonify({"result": "No selectedChatName provided in the request."}), 400

        response_text = ""

        if file:
            try:
                # Handle image file
                filename = secure_filename(file.filename)
                file_path = os.path.join('temp', filename)
                file.save(file_path)

                # Ensure it's an image file before opening
                if filename.lower().endswith(('png', 'jpg', 'jpeg', 'gif')):
                    sample_file = Image.open(file_path)
                    # print(f"Image file {filename} opened successfully.")
                else:
                    # print(f"Invalid image format: {filename}")
                    return jsonify({"result": "Uploaded file is not a valid image format."}), 400

                # Only image and text
                prompt = f"{text}"
                response = chat.send_message(
                    [prompt, sample_file], stream=True)
                os.remove(file_path)  # Remove the image file after processing

            except Exception as e:
                # print(f"Error processing image file: {str(e)}")
                return jsonify({"result": f"Error processing image file: {str(e)}"}), 500

        elif audioFile:
            try:
                audio_filename = secure_filename(audioFile.filename)
                audio_file_path = os.path.join('temp', audio_filename)
                audioFile.save(audio_file_path)

                with open(audio_file_path, 'rb') as audio_file:
                    audio_data = audio_file.read()

                    # Combine text, image, and audio input
                    prompt = f"{text}"
                    # print(f"Sending audio file -> {audio_file_path}")

                    # Wrap audio data in a dictionary with MIME type and data
                    audio_payload = {
                        "mime_type": "audio/mp3",
                        "data": audio_data
                    }

                    response = chat.send_message(
                        [prompt, audio_payload], stream=True)

                os.remove(audio_file_path)  # Clean up files after processing

            except Exception as e:
                # print(f"Error processing audio file: {str(e)}")
                return jsonify({"result": f"Error processing audio file: {str(e)}"}), 500

        else:
            # Only text is provided
            try:
                prompt = f"{text}"
                response = chat.send_message(prompt, stream=True)
            except Exception as e:
                # print(f"Error processing text: {str(e)}")
                return jsonify({"result": f"Error processing text: {str(e)}"}), 500

        def generate():
            try:
                for chunk in response:
                    yield chunk.text
            except Exception as e:
                # print(f"Error generating response: {str(e)}")
                yield f"Error generating response: {str(e)}"

        # Store chat history in Firebase
        uid = request.cookies.get('uid')
        if not uid:
            return jsonify({"result": "User not authenticated."}), 401

        chat_ref = db.reference(
            f'users/{uid}/chats/{selectedChatName}/history')

        chat_history = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'user_message': text,
            'response_message': "".join(generate())
        }

        chat_ref.push(chat_history)

        return Response(generate(), content_type='text/plain')

    except Exception as e:
        # print(f"Error in /api endpoint: {str(e)}")
        return jsonify({"result": f"An error occurred: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)
