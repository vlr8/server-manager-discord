import os
from pprint import pprint
import logging
import traceback
import time
import json
import datetime
import requests
from bs4 import BeautifulSoup
import re
import common.discord as discord
import common.logger as logger
from instagram.instagram import Instagram
import random  # Added for randomization
import pickle  # Added for saving/loading queue state
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("insta_monitor_log.log"), logging.StreamHandler()]
)
logger = logging.getLogger('insta_monitor_log')

# File to store the queue state
QUEUE_STATE_FILE = 'instagram_queue_state.pkl'


def extract_instagram_image_urls(html_content):
    # Create BeautifulSoup object
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Check if this is a video, if so we can't repost it
    # Method 2: Find span elements containing text that includes "Original audio" (more flexible)
    spans = soup.find_all('span', string=lambda text: text and 'Original audio' in text)
    if (len(spans) > 0):
        raise Exception('post is a video, can not retrieve')
    

    # Method 1: Find by alt text pattern
    image_elements = soup.find_all('img', alt=lambda value: value and "Photo by " in value)
    
    logger.info(f"parsing out image_elements from return content...")
    # Method 2: Find by parent div class pattern
    aagv_divs = soup.find_all('div', class_=lambda x: x and '_aagv' in x)
    for div in aagv_divs:
        img = div.find('img')
        if img and img not in image_elements:
            image_elements.append(img)
    
    # Method 3: Find by container structure
    ul_acay = soup.find('ul', class_=lambda x: x and '_acay' in x)
    if ul_acay:
        img_elements_in_ul = ul_acay.find_all('img')
        for img in img_elements_in_ul:
            if img not in image_elements:
                image_elements.append(img)
    
    # Extract the src attribute from each image element
    image_urls = []
    for img in image_elements:
        src = img.get('src')
        if src and src not in image_urls:
            image_urls.append(src)
    
    return image_urls

def extract_main_profile_info(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')

    # Dictionary to store profile information
    profile_info = {
        'username': None,
        'profile_picture_url': None
    }
        
    try:
        # Alternative approach if the above doesn't work
        profile_imgs = soup.find_all('img', alt=lambda value: value and "profile picture" in value)
        for img in profile_imgs:
            # Check if this img is preceded by a canvas within the same parent container
            parent = img.parent
            while parent and parent.name != 'body':
                if parent.find('canvas'):
                    profile_info['username'] = img.get('alt').split('profile picture')[0].strip()
                    profile_info['profile_picture_url'] = img.get('src')
                    return profile_info
                parent = parent.parent
    except Exception as e:
        logger.error(f"could not get profile name or pic for one of the users")
        return None

# Example usage with Selenium (for JavaScript-rendered content)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time

def get_instagram_page_with_selenium(url):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')

    # Add user agent to make detection harder
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36')

    # uncomment out for logging
    options.add_argument('--enable-logging')
    options.add_argument('--v=1')

    # Disable automation flags
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)
    driver = webdriver.Chrome(options=options)
    
    try:
        # Set page load timeout
        driver.set_page_load_timeout(30)
        # Navigate to the URL
        driver.get(url)
        # Wait for specific Instagram elements to load
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "img"))
            )
        except:
            print("Timed out waiting for page elements to load")
        
        # Additional wait for dynamic content
        time.sleep(3)

        # Parse and add cookies
        cookies = [
            {'name': 'csrftoken', 'value': 'MFufzNI4i7z7ao10kFN5zlGsC2tjU86h', 'domain': '.instagram.com'},
            {'name': 'datr', 'value': 'tNDGZknet3k7-WVRpQfgEe1X', 'domain': '.instagram.com'},
            {'name': 'dpr', 'value': '1.5', 'domain': '.instagram.com'},
            {'name': 'ds_user_id', 'value': '26694167676', 'domain': '.instagram.com'},
            {'name': 'fbm_124024574287414', 'value': 'base_domain=.instagram.com', 'domain': '.instagram.com'},
            {'name': 'ig_did', 'value': 'FD19E7F2-5C00-4730-B2FE-4640634810E2', 'domain': '.instagram.com'},
            {'name': 'mid', 'value': 'ZsbQtAALAAHs041vw6CB3oQpslvS', 'domain': '.instagram.com'},
            {'name': 'ps_l', 'value': '1', 'domain': '.instagram.com'},
            {'name': 'ps_n', 'value': '1', 'domain': '.instagram.com'},
            {'name': 'rur', 'value': '"NHA\\05426694167676\\0541776261585:01f72d5bc198eafb94569ec8ec2fa9653ede1b7cabce6701a53355d9146a634729385266"', 'domain': '.instagram.com'},
            {'name': 'sessionid', 'value': '26694167676%3Ayw79JVR5H7dRrW%3A27%3AAYe8-fTus1zzMwwYdvEkQT7vV0Tui8XT6-QDlsbZfhJc', 'domain': '.instagram.com'},
            {'name': 'wd', 'value': '1280x613', 'domain': '.instagram.com'}
        ]
        
        for cookie in cookies:
            driver.add_cookie(cookie)
        # refresh to apply cookie
        driver.refresh()

        # Scroll to load more content if needed
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(2)

        page_source = driver.page_source
        return page_source
    finally:
        driver.quit()

def save_queue_state(post_queue, next_post_time):
    """Save the current queue state to a file"""
    queue_state = {
        'post_queue': post_queue,
        'next_post_time': next_post_time,
        'saved_at': datetime.datetime.now().isoformat()
    }
    
    try:
        with open(QUEUE_STATE_FILE, 'wb') as f:
            pickle.dump(queue_state, f)
        logger.info(f"Saved queue state with {len(post_queue)} posts to {QUEUE_STATE_FILE}")
        
        # Also save a human-readable version for inspection
        with open(QUEUE_STATE_FILE + '.json', 'w') as f:
            # Create a simplified version that's JSON serializable
            json_safe_queue = []
            for post in post_queue:
                # Make a copy to avoid modifying the original
                json_post = post.copy()
                # Convert datetime objects to strings
                if isinstance(json_post.get('date'), datetime.datetime):
                    json_post['date'] = json_post['date'].isoformat()
                json_safe_queue.append(json_post)
            
            json_state = {
                'post_queue': json_safe_queue,
                'next_post_time': next_post_time,
                'saved_at': queue_state['saved_at'],
                'queue_length': len(post_queue)
            }
            json.dump(json_state, f, indent=2)
        
        return True
    except Exception as e:
        logger.error(f"Failed to save queue state: {str(e)}")
        logger.error(traceback.format_exc())
        return False


def load_queue_state():
    """Load the queue state from a file if it exists"""
    if not os.path.exists(QUEUE_STATE_FILE):
        logger.info(f"No queue state file found at {QUEUE_STATE_FILE}")
        return None, None
    
    try:
        with open(QUEUE_STATE_FILE, 'rb') as f:
            queue_state = pickle.load(f)
        
        post_queue = queue_state.get('post_queue', [])
        next_post_time = queue_state.get('next_post_time')
        saved_at = queue_state.get('saved_at')
        
        logger.info(f"Loaded queue state from {QUEUE_STATE_FILE}")
        logger.info(f"Queue contains {len(post_queue)} posts")
        logger.info(f"Queue was saved at {saved_at}")
        
        return post_queue, next_post_time
    except Exception as e:
        logger.error(f"Failed to load queue state: {str(e)}")
        logger.error(traceback.format_exc())
        return None, None
    


def run_bot():
    global post_ids

    Monitor = Instagram(
        name='instagram',
        usernames=[
            'tr4nbie',
            'tslurps',
            '1ofthedolls',
            # 'bingbongdotcom',
            #'chaseicon',
            #'hunterschafer',
            #'thefakehazel',
            #'lenacassandre',
            #'aoife_bee_',
            ##'autogyniphiles_anonymous',
            #'trans_misogynist',
            'rosejupiter',
            # 'transsmemes',
            # 'trans__memes_',
            'czech.hunter.schafer',
            # 'transgirlhell',
            #'clumsy.memes',
            #'transtrender666',
            #'transgender.gamer.girl',
            #'rhizomatic_memer',
            #'trooncelfatale',
            #'user_goes_to_kether',
            # 't.slur.memes',
            #'attis.emasculate',
            #'oncloud.e',
            # 'doll.deranged',
            #'based.transgirl',
            #'sissy.allegations'
        ],
        post_ids=post_ids.get('instagram', []),
        channel_ids=[
            # 1158203872423186461,  # trannerland
            # 1128797444323426394,  # debug
            # 1306403996550041650 # mod channel
            1158681076504469514 # tranner-central
        ],
    )

    repost_to_discord(Monitor)


def repost_to_discord(Monitor):
    # How often to check for new posts (once per day = 86400 seconds)
    check_interval = 86400
    # Time between individual posts (60 minutes = 3600 seconds)
    # 7200 = 2 hours
    post_interval = 7200
    
    # Try to load existing queue state
    post_queue, loaded_next_post_time = load_queue_state()
    
    # Initialize queue if none was loaded
    if post_queue is None:
        post_queue = []
        next_post_time = time.time()
    else:
        next_post_time = loaded_next_post_time
        # If the next post time is in the past, set it to now
        if next_post_time < time.time():
            next_post_time = time.time()
    
    # Flag to track if we should save the queue state
    queue_modified = False
    random.shuffle(post_queue)

    # Access the global posted_ids
    global post_ids
    global posted_ids
    if 'instagram' not in posted_ids:
        posted_ids['instagram'] = []
    
    while True:
        try:
            current_time = time.time()
            
            # If the queue is empty, fetch new posts
            if not post_queue:
                # Log the current time for reference
                current_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logger.info(f"[{current_datetime}] Post queue empty, checking Instagram for new content")
                
                # Fetch new posts
                posts = Monitor.fetch_posts()
                logger.info(f"Fetched {len(posts)} posts from {Monitor.name}")

                # Remove posts that have already been posted
                new_posts = [x for x in posts if x['id'] not in Monitor.post_ids]
                logger.info(f"Found {len(new_posts)} new posts to add to queue")
                
                # Add the new posts to the list of tracked post IDs
                Monitor.post_ids += [post['id'] for post in new_posts]
                
                # Save the updated list immediately to prevent re-posting on restart
                post_ids[Monitor.name] = Monitor.post_ids
                with open('post_ids.json', 'w') as f:
                    json.dump(post_ids, f, indent=4)
                
                # If no new posts, sleep and check again later
                if not new_posts:
                    next_check_time = current_time + check_interval
                    next_check_str = datetime.datetime.fromtimestamp(next_check_time).strftime("%Y-%m-%d %H:%M:%S")
                    logger.info(f"No new posts found. Next check at {next_check_str}")
                    time.sleep(check_interval)
                    continue
                
                # Sort posts by date (oldest first)
                # new_posts = sorted(new_posts, key=lambda x: x['date'])
                random.shuffle(new_posts)
                
                # Process each post to handle multiple images
                expanded_queue = []
                for post in new_posts:
                    try:
                        # Get all images from the post
                        page_source = get_instagram_page_with_selenium(post['url'])
                        image_urls = extract_instagram_image_urls(page_source)
                        profile_info = extract_main_profile_info(page_source)
                        profile_pic = profile_info['profile_picture_url']
                        username = profile_info['username']
                        
                        if image_urls:
                            # Create a separate queue item for each image in the post
                            for i, img_url in enumerate(image_urls):
                                # Copy the post data but with specific image URL
                                post_copy = post.copy()
                                post_copy['image_url'] = img_url
                                post_copy['image_index'] = i + 1
                                post_copy['total_images'] = len(image_urls)
                                post_copy['profile_pic'] = profile_pic
                                post_copy['username'] = username
                                expanded_queue.append(post_copy)
                            logger.info(f"Added post {post['id']} with {len(image_urls)} images to queue")
                        else:
                            # If no images found, still add the post with url_only=True
                            post['url_only'] = True
                            expanded_queue.append(post)
                            logger.info(f"Added post {post['id']} with no images to queue")
                    except Exception as e:
                        logger.error(f"Error processing post {post['id']}: {str(e)}")
                        # Add the post anyway, so we'll use url_only when posting
                        post['url_only'] = True
                        expanded_queue.append(post)
                
                # Add all processed SHUFFLED posts to the queue
                random.shuffle(expanded_queue)
                post_queue.extend(expanded_queue)
                random.shuffle(post_queue)
                
                # Set the next post time if it's not already set
                if next_post_time < current_time:
                    next_post_time = current_time
                
                logger.info(f"Queue now contains {len(post_queue)} posts to be sent every 30 minutes")

                # Save the queue state since we modified it
                queue_modified = True
                save_queue_state(post_queue, next_post_time)
            
            # Check if it's time to post the next item
            if current_time >= next_post_time and post_queue:
                # Get the next post from queue
                post = post_queue.pop(0)
                
                # Format timestamps for logging
                post_datetime = post['date'].strftime("%Y-%m-%d %H:%M:%S")
                current_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                logger.info(f"[{current_datetime}] Posting 1 item to Discord (originally from {post_datetime})")
                logger.info(f"Post URL: {post['url']}")
                
                try:
                    # Check if this post already has a processed image_url
                    if 'image_url' in post:
                        # Post with image from the expanded queue
                        image_suffix = ""
                        if 'total_images' in post and post['total_images'] > 1:
                            image_suffix = f" (Image {post['image_index']}/{post['total_images']})"
                        
                        # Create a unique ID for this post+image combination
                        unique_post_id = f"{post['url']}{image_suffix}"
                        # Check if this unique ID has already been posted
                        if unique_post_id in posted_ids['instagram']:
                            logger.info(f"Skipping already posted image: {unique_post_id}")
                            continue

                        discord.post(
                            url_only=False,
                            url=post['url'],
                            image=post['image_url'],
                            thumbnail=post['profile_pic'],
                            site_name='instagram',
                            site_icon='https://i.imgur.com/OWdUupI.png',
                            description=post['username'] + ' repost from ' + post['url'],
                            channel_ids=Monitor.channel_ids,
                        )

                        # Add the unique ID to posted_ids and save
                        posted_ids['instagram'].append(unique_post_id)
                        with open('posted_ids.json', 'w') as f:
                            json.dump(posted_ids, f, indent=4)

                        logger.info(f"Successfully posted image {post.get('image_index', 1)} of {post.get('total_images', 1)} to Discord")
                        logger.info(f"Added unique ID to posted_ids: {unique_post_id}")
                    elif post.get('url_only', False):
                        # Create a unique ID for URL-only posts
                        unique_post_id = f"{post['url']} (URL only)"
                        # Check if this unique ID has already been posted
                        if unique_post_id in posted_ids['instagram']:
                            logger.info(f"Skipping already posted URL: {unique_post_id}")
                            continue

                        # Post URL only if marked as url_only
                        discord.post(
                            url_only=True,
                            url=post['url'],
                            channel_ids=Monitor.channel_ids,
                        )

                        # Add the unique ID to posted_ids and save
                        posted_ids['instagram'].append(unique_post_id)
                        with open('posted_ids.json', 'w') as f:
                            json.dump(posted_ids, f, indent=4)

                        logger.info(f"Posted URL-only to Discord (could not extract images)")
                        logger.info(f"Added unique ID to posted_ids: {unique_post_id}")
                    else:
                        raise ValueError("No images found in the Instagram post")
                except ValueError as e:
                    # If we can't get the image, fall back to posting just the URL
                    # logger.error(f"Failed to get image, falling back to URL only: {e}")
                    logger.error(f"Failed to get image, giving up with: {e}")
                
                # Calculate and display queue status
                remaining_time = len(post_queue) * post_interval / 3600  # hours
                logger.info(f"Queue status: {len(post_queue)} posts remaining (~{remaining_time:.1f} hours of content)")
                
                # Set time for next post
                next_post_time = current_time + post_interval
                next_post_str = datetime.datetime.fromtimestamp(next_post_time).strftime("%H:%M:%S")
                logger.info(f"Next post scheduled for {next_post_str}")

                # Save the queue state after posting
                if queue_modified:
                    save_queue_state(post_queue, next_post_time)
                    queue_modified = False
            
            # If queue is empty after posting, need to wait until next daily check
            elif not post_queue:
                # Calculate time until next check
                time_until_check = (next_post_time + check_interval) - current_time
                logger.info(f"Queue empty. Next Instagram check in {time_until_check/3600:.1f} hours")
                time.sleep(min(post_interval, time_until_check))  # Sleep at most 30 minutes
            else:
                # Wait until next scheduled post time
                wait_time = next_post_time - current_time
                logger.info(f"Waiting {wait_time/60:.1f} minutes until next post")
                time.sleep(min(wait_time, 60))  # Sleep at most 1 minute to allow for script interruption

        except KeyboardInterrupt:
            # Save queue state when script is interrupted
            logger.info("Script interrupted. Saving queue state before exiting...")
            save_queue_state(post_queue, next_post_time)
            raise
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"Error occurred: {str(e)}")
            
            # Save the queue state if there was an error
            if queue_modified:
                logger.info("Saving queue state after error...")
                save_queue_state(post_queue, next_post_time)
                queue_modified = False
                
            # If an error occurs, wait before trying again
            logger.info("Waiting 5 minutes before retrying due to error")
            time.sleep(300)


def debug():
    global post_ids
    global posted_ids
    
    # Test the image fetching functionality with the URL provided
    test_url = "https://www.instagram.com/p/C5PYJUTPkwS/"  # Use a real Instagram post URL
    try:
        # run_bot()
        content = get_instagram_page_with_selenium(test_url)
        image_details = extract_instagram_image_urls(content)
        print(image_details)
    except ValueError as e:
        print(f"Error: {e}")
    
    pass


if __name__ == '__main__':
    # Check if BeautifulSoup is installed, if not, warn the user
    try:
        import bs4
    except ImportError:
        print("ERROR: BeautifulSoup is not installed. Please install it with:")
        print("pip install beautifulsoup4")
        exit(1)
    
    # Check if regex module is available
    try:
        import re
    except ImportError:
        print("ERROR: Regular expression module not available")
        exit(1)
        
    # Open the post_ids file if it exists
    if os.path.exists('post_ids.json'):
        with open('post_ids.json', 'r') as pf:
            post_ids = json.load(pf)
            logger.info(f"Loaded {len(post_ids.get('instagram', []))} Instagram post IDs from post_ids.json")
    else:
        with open('post_ids.json', 'w') as pf:
            json.dump({}, pf)
            post_ids = {}
            logger.info("Created new post_ids.json file")
    if os.path.exists('posted_ids.json'):
        with open('posted_ids.json', 'r') as pf:
            posted_ids = json.load(pf)
            logger.info(f"Loaded poasted {len(posted_ids.get('instagram', []))} Instagram post IDs from posted_ids.json")
    else:
        with open('posted_ids.json', 'w') as pf:
            json.dump({}, pf)
            posted_ids = {}
            logger.info("Created new posted_ids.json file")

    # Check if this is debug mode
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--debug':
        debug()
    else:
        run_bot()