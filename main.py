import requests
import csv
from dotenv import load_dotenv
import os
import time
import base64
import gspread
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()

BEARER_TOKEN = os.getenv('BEARER_TOKEN_2')

# スプレッドシートの認証設定
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

# GitHub Actions で credentials.json を作成（Base64形式から）
google_creds_base64 = os.getenv("GOOGLE_CREDENTIALS_JSON")
if google_creds_base64:
    with open("credentials.json", "wb") as f:
        f.write(base64.b64decode(google_creds_base64))
    credentials_file = "credentials.json"
else:
    credentials_file = "xscraper-457604-69659ff09a28.json"  # ローカル用

credentials = ServiceAccountCredentials.from_json_keyfile_name(credentials_file, scope)
client = gspread.authorize(credentials)
sheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID")).sheet1

# X APIのURL
BASE_URL = 'https://api.twitter.com/2/tweets/search/recent'
query = '業務委託 マーケ -is:retweet'

headers = {
    'Authorization': f'Bearer {BEARER_TOKEN}',
}

tweet_ids = set()

def fetch_tweets(query, next_token=None):
    url = (
        f'{BASE_URL}?query={query}'
        f'&tweet.fields=author_id,created_at'
        f'&expansions=author_id'
        f'&user.fields=username,description'
        f'&max_results=100'
    )
    if next_token:
        url += f'&next_token={next_token}'

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    elif response.status_code == 429:
        reset_time = int(response.headers.get('x-rate-limit-reset', time.time()))
        wait_time = reset_time - time.time() + 10
        print(f"レート制限に達しました。{wait_time:.0f}秒後に再試行します...")
        time.sleep(wait_time)
        return fetch_tweets(query, next_token)
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
        return None

def append_to_google_sheet(rows):
    for row in rows:
        sheet.append_row(row)

    with open('x_okonogi_250407.csv', mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if file.tell() == 0:
            headers = ['Tweet', 'Account Name', 'Profile', 'Created At']
            writer.writerow(headers)
        writer.writerows(rows)

def send_slack_notification(rows):
    webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    if not rows:
        return

    chunk_size = 5
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        messages = []

        for row in chunk:
            tweet_text, username, profile, created_at = row
            message = (
                f"👤 @{username}\n"
                f" {profile}\n"
                f" {created_at}\n"
                f"💬 {tweet_text}\n"
                f"{'-'*30}"
            )
            messages.append(message)

        full_message = "新しいツイートまとめ（{}件）\n\n{}".format(len(chunk), "\n\n".join(messages))

        payload = {'text': full_message}
        response = requests.post(webhook_url, json=payload)

        if response.status_code != 200:
            print(f"Slack通知失敗（chunk {i}）: {response.text}")
        time.sleep(1)  # Slackの制限回避のために少し待機

def main():
    next_token = None
    new_rows = []

    while True:
        data = fetch_tweets(query, next_token)

        if data:
            tweets = data.get('data', [])
            users = data.get('includes', {}).get('users', [])
            users_dict = {user['id']: user for user in users}

            for tweet in tweets:
                tweet_id = tweet['id']
                if tweet_id in tweet_ids:
                    continue
                tweet_ids.add(tweet_id)

                user_id = tweet['author_id']
                user = users_dict.get(user_id, {})
                row = [
                    tweet['text'],
                    user.get('username', 'N/A'),
                    user.get('description', 'N/A'),
                    tweet.get('created_at', 'N/A'),
                ]
                new_rows.append(row)

            next_token = data.get('meta', {}).get('next_token')
            if not next_token:
                break
        else:
            break

    if new_rows:
        append_to_google_sheet(new_rows)
        send_slack_notification(new_rows)
        print(f"{len(new_rows)}行をGoogleシートに追加しました。")
    else:
        print("新しいツイートはありません。")

if __name__ == '__main__':
    main()
