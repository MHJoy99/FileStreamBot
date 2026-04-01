<h1 align="center">FileStreamBot</h1>
<p align="center">
  <a href="https://github.com/Avipatilpro/FileStreamBot">
    <img src="https://graph.org/file/80d1f94e81bbc1acadb36.jpg" alt="Cover Image" width="550">
  </a>
</p>  
  <p align="center">
   </strong></a>
    <br><b>
    <a href="https://github.com/Avipatilpro/FileStreamBot/issues">Report a Bug</a>
    |
    <a href="https://github.com/Avipatilpro/FileStreamBot/issues">Request Feature</a></b>
  </p>



### 🍁 About :

<p align="center">
    <a href="https://github.com/Avipatilpro/FileStreamBot">
        <img src="https://i.ibb.co/ZJzJ9Hq/link-3x.png" height="100" width="100" alt="FileStreamBot Logo">
    </a>
</p>
<p align='center'>
  This bot provides stream links for Telegram files without the necessity of waiting for the download to complete, offering the ability to store files.
</p>

### ♢ Project Docs :

- [VPS Deployment Guide](./VPS_DEPLOYMENT.md)
- [Current Setup Notes](./SETUP_NOTES.md)
- [Admin Website Notes](./ADMIN_WEBSITE_NOTES.md)
- [Performance Notes](./PERFORMANCE_NOTES.md)

### ♢ Current Project Features :

- Telegram direct links and stream links for uploaded files
- Private admin website with login and dashboard
- M3U playlist creation and export from the admin panel
- Library scanning and tracked-source sync using a user session string
- Direct HTTP ranged streaming from Telegram through the web server


### ♢ How to Deploy :

<i>Either you could locally host, VPS, or deploy on [Heroku](https://heroku.com)</i>

<p><b>Recommended for a fresh server:</b> follow the <a href="./VPS_DEPLOYMENT.md">VPS Deployment Guide</a>.</p>

#### ♢ Click on This Drop-down and get more details

<br>
<details>
  <summary><b>Deploy on VPS (Recommended) :</b></summary>

- Use the repo guide: [VPS_DEPLOYMENT.md](./VPS_DEPLOYMENT.md)
- This is the current recommended path for a fresh Ubuntu VPS
- It includes `.env`, `systemd`, firewall, and health-check steps

</details>

<details>
  <summary><b>Deploy on Heroku (Paid)  :</b></summary>

- Fork This Repo
- Click on Deploy Easily
- Press the below button to Fast deploy on Heroku


   [![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy)
- Go to <a href="#mandatory-vars">variables tab</a> for more info on setting up environmental variables. </details>

<details>
  <summary><b>Deploy Locally :</b></summary>
<br>

```sh
git clone https://github.com/avipatilpro/FileStreamBot
cd FileStreamBot
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 -m FileStream
```

- To stop the whole bot,
 do <kbd>CTRL</kbd>+<kbd>C</kbd>

- If you want to run this bot 24/7 on the VPS, follow these steps.
```sh
sudo apt install tmux -y
tmux
python3 -m FileStream
```
- now you can close the VPS and the bot will run on it.

  </details>

<details>
  <summary><b>Deploy using Docker :</b></summary>
<br>
* Clone the repository:
```sh
git clone https://github.com/avipatilpro/FileStreamBot
cd FileStreamBot
```
* Build own Docker image:
```sh
docker build -t file-stream .
```

* Create ENV and Start Container:
```sh
docker run -d --restart unless-stopped --name fsb \
-v /PATH/TO/.env:/app/.env \
-p 8000:8000 \
file-stream
```
- if you need to change the variables in .env file after your bot was already started, all you need to do is restart the container for the bot settings to get updated:
```sh
docker restart fsb
```

  </details>

<details>
  <summary><b>Setting up things :</b></summary>


If you're on Heroku, just add these in the Environmental Variables
or if you're Locally hosting, create a file named `.env` in the root directory and add all the variables there.
An example of `.env` file:

```sh
API_ID = 789456
API_HASH = ysx275f9638x896g43sfzx65
BOT_TOKEN = 12345678:your_bot_token
OWNER_ID = 987456321
ULOG_CHANNEL = -100123456789
FLOG_CHANNEL = -100123456789
DATABASE_URL = mongodb://admin:pass@192.168.27.1
SESSION_NAME = FileStream
FQDN = stream.example.com
HAS_SSL = False
NO_PORT = False
PORT = 18180
BIND_ADDRESS = 0.0.0.0
AUTH_USERS = 987456321
WORKERS = 6
USER_SESSION_STRING = your_user_session_string
MULTI_TOKEN1 = 12345678:bot_token_multi_client_1
MULTI_TOKEN2 = 12345678:bot_token_multi_client_2
ADMIN_USERNAME = admin
ADMIN_PASSWORD = change_this_password
WEB_SESSION_SECRET = change_this_secret
```

Important:

- The bot must be admin in `FLOG_CHANNEL` and `ULOG_CHANNEL`
- Any extra `MULTI_TOKEN*` client or session must also be able to access `FLOG_CHANNEL`
</details>


<details>
  <summary><b>Vars and Details :</b></summary>

#### 📝 Mandatory Vars :

* `API_ID`: API ID of your Telegram account, can be obtained from [My Telegram](https://my.telegram.org). `int`
* `API_HASH`: API hash of your Telegram account, can be obtained from [My Telegram](https://my.telegram.org). `str`
* `OWNER_ID`: Your Telegram User ID, Send `/id` to [@missrose_bot](https://telegram.dog/MissRose_bot) to get Your Telegram User ID `int`
* `BOT_TOKEN`: Telegram API token of your bot, can be obtained from [@BotFather](https://t.me/BotFather). `str`
* `FLOG_CHANNEL`: ID of the channel where bot will store all Files from users `int`.
* `ULOG_CHANNEL`: ID of the channel where bot will send logs of New Users`int`.
* `WORKERS`: Number of maximum concurrent workers for handling incoming updates. Defaults to `6`. `int`
* `DATABASE_URL`: MongoDB URI for saving User Data and Files List created by user. `str`
* `FQDN`: A Fully Qualified Domain Name if present without http/s. Defaults to `BIND_ADDRESS`. `str`

#### 🗼 MultiClient Vars :
* `MULTI_TOKEN1`: Add your first bot token or session strings here. `str`
* `MULTI_TOKEN2`: Add your second bot token or session strings here. `str`
* `USER_SESSION_STRING`: Required for full chat-history scanning and tracked source sync. `str`

#### 🪐 Optional Vars :

* `UPDATES_CHANNEL`: Channel Username without `@` to set channel as Update Channel `str`
* `FORCE_SUB_ID`: Force Sub Channel ID, if you want to use Force Sub. start with `-100` `int
* `FORCE_SUB`: Set to True, so every user have to Join update channel to use the bot. `bool`
* `AUTH_USERS`: Put authorized user IDs to use bot, separated by <kbd>Space</kbd>. `int`
* `SLEEP_THRESHOLD`: Set global flood wait threshold, auto-retry requests under 60s. `int`
* `SESSION_NAME`: Name for the Database created on your MongoDB. Defaults to `FileStream`. `str`
* `FILE_PIC`: To set Image at `/files` command. Defaults to pre-set image. `str`
* `START_PIC`: To set Image at `/start` command. Defaults to pre-set image. `str`
* `VERIFY_PIC`: To set Image at Force Sub Verification. Defaults to pre-set image. `str`
* `PORT`: The port that you want your webapp to be listened to. Defaults to `8080`. `int`
* `BIND_ADDRESS`: Your server bind adress. Defauls to `0.0.0.0`. `int`
* `MODE`: Should be set to `secondary` if you only want to use the server for serving files. `str`
* `NO_PORT`: (True/False) Set PORT to 80 or 443 hide port display; ignore if on Heroku. Defaults to `False`.
* `HAS_SSL`: (can be either `True` or `False`) If you want the generated links in https format. Defaults to `False`.
* `ADMIN_USERNAME`: Legacy admin website username. `str`
* `ADMIN_PASSWORD`: Legacy admin website password. `str`
* `ADMIN_CREDENTIALS`: Comma-separated `username:password` pairs for web admin logins. `str`
* `WEB_SESSION_SECRET`: Cookie signing secret for admin sessions. Defaults to `BOT_TOKEN`. `str`
* `WEB_SESSION_TTL`: Admin session lifetime in seconds. Defaults to `2592000`. `int`
* `BUNDLE_FALLBACK_CHAT`: Telegram destination for website bundle delivery fallback. `int`
* `TMDB_API_KEY`: Optional TMDb API key for media metadata helpers. `str`
* `TMDB_READ_ACCESS_TOKEN`: Optional TMDb read access token. `str`

</details>

<details>
  <summary><b>How to Use :</b></summary>

:warning: **Before using the  bot, don't forget to add the bot to the `LOG_CHANNEL` as an Admin**

:warning: **If you use extra `MULTI_TOKEN*` clients or session strings, they must also be able to access the `LOG_CHANNEL`**
 
#### ‍☠️ Bot Commands :

```sh
/start      : To check the bot is alive or not.
/help       : To Get Help Message.
/about      : To check About the Bot.
/files      : To Get All Files List of User.
/del        : To Delete Files from DB with FileID. [ADMIN]
/ban        : To Ban Any Channel or User to use bot. [ADMIN]
/unban      : To Unban Any Channel or User to use bot. [ADMIN]
/status     : To Get Bot Status and Total Users. [ADMIN]
/broadcast  : To Broadcast any message to all users of bot. [ADMIN]
```

#### 🍟 Channel Support :

*Bot also Supported with Channels. Just add bot Channel as Admin. If any new file comes in Channel it will edit it with **Get Download Link** Button.*

#### 🌐 Web Admin :

* Admin login is available at `/admin/login`
* Admin dashboard is available at `/admin`
* The dashboard can create `.m3u` playlist links and export direct links
* See [ADMIN_WEBSITE_NOTES.md](./ADMIN_WEBSITE_NOTES.md) for details

</details>

### ❤️ Thanks To :

- [**Me**](https://github.com/AvishkarPatil) : Owner of This FileStreamBot
- [**Deekshith SH**](https://github.com/DeekshithSH) : for some modules.
- [**EverythingSuckz**](https://github.com/EverythingSuckz) : for his [FileStreamBot](https://github.com/EverythingSuckz/FileStreamBot)
- [**Biisal**](https://github.com/biisal) : for Stream Page UI

---
<h4 align='center'>© 2024 Aνιѕнкαя Pαтιℓ</h4>


