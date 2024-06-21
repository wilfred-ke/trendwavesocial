import json
from django.utils.timezone import now
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect
import tempfile
import mimetypes
from django.http import HttpResponse, Http404
from django.shortcuts import redirect, render
from django.contrib.auth import logout
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Image, User, TheProfile, LikeImage, FollowersCount, Comment, RecentSearch
from .forms import CommentForm
from django.urls import reverse
from django.contrib.auth import authenticate
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings
from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.urls import reverse_lazy, reverse
from .forms import ImageForm
from django.db.models import Q
from itertools import chain
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.conf import settings
import uuid
import os
import re
import random
import magic
import moviepy.editor as mp
from moviepy import *

IMAGE_FILE_TYPES = ['png', 'jpg', 'jpeg']


def validate_file_mimetype(file):
    accept = [
        'image/png', 'image/jpg', 'image/jpeg',
        'video/mp4', 'video/webm', 'video/avi',
        'video/mov', 'video/gif', 'image/gif',
        'video/mkv', 'video/ogg', 'video/3gp'
    ]
    file_mime_type = magic.from_buffer(file.read(1024), mime=True)
    file.seek(0)  # Reset file pointer after reading
    if file_mime_type not in accept:
        raise ValidationError("Unsupported file format")


def validate_video_duration(file_path):
    video = mp.VideoFileClip(file_path)
    if video.duration > 61:
        raise ValidationError("Video length should not exceed 1 minute.")

def is_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'

def handle_ajax_response(request, message, status):
    if request.is_ajax():
        return JsonResponse({'error' if status != 200 else 'message': message}, status=status)
    messages.error(request, message)
    return redirect('upload')

def checkpath(request, x):
    if not os.path.exists(x.file.path):
        message = "Failed to save the file. Please try again."
        return handle_ajax_response(request, message, 500)

@login_required
def upload(request):
    if request.method == "POST":
        user = request.user
        file = request.FILES.get('file_upload')
        caption = request.POST['caption']

        try:
            # Validate file type
            validate_file_mimetype(file)

            # Save the file to a temporary location if it's a video
            if file.name.endswith(('.mp4', '.avi', '.mov', '.webm', '.mkv', '.gif', '.ogg', '.3gp')):
                temp_file_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.name)[1]) as temp_file:
                        for chunk in file.chunks():
                            temp_file.write(chunk)
                        temp_file_path = temp_file.name
                    
                    # Validate the duration of the video
                    validate_video_duration(temp_file_path)
                
                except ValidationError as e:
                    return handle_ajax_response(request, str(e), 400)
        
        except ValidationError as e:
            return handle_ajax_response(request, str(e), 400)

        # Save the file to the model
        new_post = Image.objects.create(user=user, file=file, caption=caption)
        new_post.save()
        
        if is_ajax(request):
            return JsonResponse({'message': 'File uploaded successfully!'}, status=200)
        
        return redirect('homepage')
    else:
        form = ImageForm()
    return render(request, 'upload.html', {'form': form})


def get_recent_searches_from_cookies(request):
    recent_searches_cookie = request.COOKIES.get('recent_searches')
    if recent_searches_cookie:
        return json.loads(recent_searches_cookie)
    return []


def save_search_term(request, q, recent_searches):
    if request.user.is_authenticated:
        RecentSearch.objects.update_or_create(
            user=request.user, search_term=q, defaults={'timestamp': now()}
        )
    else:
        if q not in recent_searches:
            recent_searches.append(q)
            if len(recent_searches) > 10:  # Limit to last 10 searches
                recent_searches.pop(0)


def get_search_results(q):
    multiple_q = Q(Q(caption__icontains=q) | Q(
        date__icontains=q) | Q(user__username__icontains=q))
    return Image.objects.filter(multiple_q)


def get_user_profile(request):
    if request.user.is_authenticated:
        try:
            user_object = User.objects.get(username=request.user.username)
            return TheProfile.objects.get(user=user_object)
        except TheProfile.DoesNotExist:
            return TheProfile.objects.get(profileimg=True)
    return None


def get_user_suggestions(q):
    return User.objects.filter(username__icontains=q)[:5]


def get_latest_images():
    return Image.objects.all().order_by('date')[:4]


def set_recent_searches_cookie(response, recent_searches):
    response.set_cookie('recent_searches', json.dumps(
        recent_searches), max_age=30*24*60*60)  # 30 days


def index(request):
    img = Image.objects.all().order_by('-date')
    recent_searches = get_recent_searches_from_cookies(request)
    user_suggestions = []

    if request.method == 'GET' and 'q' in request.GET:
        q = request.GET['q']
        save_search_term(request, q, recent_searches)
        img = get_search_results(q)

        if not img.exists():
            messages.info(request, f"No results found for '{q}'.")

        user_suggestions = get_user_suggestions(q)
    else:
        img = Image.objects.all().order_by('-date')

    user_profile = get_user_profile(request)
    latest_images = get_latest_images()

    response = render(request, 'index.html', {
        'img': img,
        'user_profile': user_profile,
        'latest_images': latest_images,
        'recent_searches': recent_searches,
        'user_suggestions': user_suggestions,
    })

    if not request.user.is_authenticated:
        set_recent_searches_cookie(response, recent_searches)

    return response


@login_required
def download(path):
    file_path = os.path.join(settings.MEDIA_ROOT, path)
    if os.path.exists(file_path):
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = "application/octet-stream"

        with open(file_path, 'rb') as fh:
            response = HttpResponse(fh.read(), content_type=mime_type)
            response['Content-Disposition'] = 'inline; filename=' + \
                os.path.basename(file_path)
            return response

    raise Http404

# Function to generate a token
def generate_token():
    return PasswordResetTokenGenerator()

# Function to check if password is strong
def is_strong_password(password):
    if len(password) < 8:
        return False
    has_upper = False
    has_lower = False
    has_digit = False
    has_special = False
    special_characters = "!@#$%^&*()-_=+[{]}\\|;:'\",<.>/?"
    
    for char in password:
        if char.isupper():
            has_upper = True
        elif char.islower():
            has_lower = True
        elif char.isdigit():
            has_digit = True
        elif char in special_characters:
            has_special = True
    
    return has_upper and has_lower and has_digit and has_special


def signup(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        password2 = request.POST['password2']

        if User.objects.filter(username=username).exists():
            messages.error(
                request, 'Username Already Exists! Please try another username')
            return render(request, 'signup.html')

        elif len(username) > 10:
            messages.error(request, 'Username must not exceed 10 characters')
            return render(request, 'signup.html')

        elif not username.isalnum():
            messages.error(request, 'Username must be Alpha-Numeric')
            return render(request, 'signup.html')

        elif password != password2:
            messages.error(request, "Passwords didn't match")
            return render(request, 'signup.html')

        elif not is_strong_password(password):
            messages.error(
                request, "Password must be at least 8 characters long and contain at least one uppercase letter, one lowercase letter, one digit, and one special character.")
            return render(request, 'signup.html')

        # Create the user
        myuser = User.objects.create_user(username=username, password=password)
        myuser.save()

        # Create a profile object for the new user
        user_model = User.objects.get(username=username)
        new_profile = TheProfile.objects.create(
            user=user_model, id_user=user_model.id)
        new_profile.save()

        messages.success(
            request, 'Your account has been successfully created. Please log in.')
        return redirect('signIn')

    return render(request, "signup.html")

regex = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'


def check(request, email):
     if (re.fullmatch(regex, email)):
         messages.info(request, 'Your email is valid')
     else:
         messages.error(request, "Your email is invalid")
         return render(request, 'signup.html')

# @login_required(login_url='signin')
def signIn(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        next_url = request.POST.get('next')

        user = authenticate(username=username, password=password)

        if user is not None:
            if user.is_active:
             login(request, user)
             if next_url:  # If 'next' parameter exists, redirect to that URL
                return redirect(next_url)
             else:
                 return redirect('homepage')
        else:
            messages.error(request, 'Credentials do not Match, Check your name and password again. OR check your email to login if you registered')
            return redirect('signIn')

    return render(request, "signIn.html")


def custom_logout(request):
    if request.user.is_authenticated:
        username = request.user.username
        request.session['username'] = username

    # Perform logout
    logout(request)

    # Check if the session variable exists before deleting it
    if 'username' in request.session:
        del request.session['username']

    messages.success(request, 'You have successfully logged out.')
    return redirect('homepage')



def about(request):
    return render(request, 'about.html')

def blogs(request):
    return render(request, 'trendwave_blogs.html')

def privacy(request):
   return render(request, 'privacy.html')

def offline(request):
    return render(request, 'offline.html')

@login_required
def user_settings(request):
   user_profile = TheProfile.objects.get(user=request.user)

   if request.method == 'POST':
      image = request.FILES.get('image')
      bio = request.POST.get('bio')
      location = request.POST.get('location')

      if image:
         user_profile.profileimg = image
      if bio:
         user_profile.bio = bio
      if location:
         user_profile.location = location

      user_profile.save()
      return redirect('user_settings')      

   return render(request, 'user_settings.html', {'user_profile': user_profile})


def like_image(request):
    next_url = request.GET.get('next', '/')

    if not request.user.is_authenticated:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            login_url = f'{reverse("login")}?next={next_url}'
            return JsonResponse({'authenticated': False, 'login_url': login_url})
        else:
            return redirect(f'{reverse("login")}?next={next_url}')

    username = request.user.username
    image_id = request.GET.get('x_id')

    image = get_object_or_404(Image, id=image_id)

    like_filter = LikeImage.objects.filter(
        image_id=image_id, username=username).first()
    
    if like_filter is None:
        new_like = LikeImage.objects.create(
            image_id=image_id, username=username)
        new_like.save()
        image.likes += 1
        image.save()
        liked = True
    else:
        like_filter.delete()
        image.likes -= 1
        image.save()
        liked = False

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'authenticated': True, 'liked': liked, 'likes': image.likes})

    return redirect(next_url + f'#image-{image_id}')

def profile(request, pk):
    user_object = get_object_or_404(User, username=pk)
    user_profile = get_object_or_404(TheProfile, user=user_object)
    comments_count = user_profile.get_comments_count()
    likes_count = user_profile.get_likes_count()
    user_posts = Image.objects.filter(user=user_object).order_by('-date')
    user_post_length = len(user_posts)

    follower = request.user.username
    user = pk

    if FollowersCount.objects.filter(follower=follower, user=user).first():
       button_text = 'UnFollow'
    else:
       button_text = 'Follow'

    user_followers = len(FollowersCount.objects.filter(user=pk))
    user_following = len(FollowersCount.objects.filter(follower=pk))

    context = {
        'comments_count': comments_count,
        'likes_count': likes_count,
        'user_object': user_object,
        'user_profile': user_profile,
        'user_posts': user_posts,
        'user_post_length': user_post_length,
        'button_text':button_text,
        'user_followers':user_followers,
        'user_following':user_following,
    }
    return render(request, 'profile.html', context)


def robots(request):
   return render(request, 'robots.txt')

@login_required
def follow(request):
   if request.method == 'POST':
      follower = request.POST['follower']
      user = request.POST['user']

      if FollowersCount.objects.filter(follower=follower, user=user).first():
         delete_follower = FollowersCount.objects.get(follower=follower, user=user)
         delete_follower.delete()
         return redirect('/profile/'+user)
      else:
         new_follower = FollowersCount.objects.create(follower=follower, user=user)
         new_follower.save()
         return redirect('/profile/'+user)
   else:
      return redirect('/')
   
# feed for user and user_following
@login_required   
def following(request):
    user_object = User.objects.get(username=request.user.username)
    user_profile = TheProfile.objects.get(user=user_object)
    user_following_list = []
    feed = []
    user_following = FollowersCount.objects.filter(follower=request.user.username)
    
    for user_follow in user_following:
        user = User.objects.get(username=user_follow.user)
        user_following_list.append(user)

    if user_following_list:  # Check if the user is following anyone
        for user in user_following_list:
            feed_lists = Image.objects.filter(user=user)
            random.shuffle(feed_lists)
            feed.append(feed_lists)
        feed_list = list(chain(*feed))
    else:
        feed_list = []  # Ensure feed_list is assigned an empty list if no following users

    # User suggestion starts
    all_users = User.objects.all()
    user_following_all = []

    for user_follow in user_following:
      user_list = User.objects.get(username=user_follow.user)
      user_following_all.append(user_list)

    new_suggestions_list = [x for x in list(all_users) if x not in list(user_following_all)]
    current_user = User.objects.filter(username=request.user.username)
    final_suggestions_list = [x for x in list(new_suggestions_list) if x not in list(current_user)]
    random.shuffle(final_suggestions_list)       

    username_profile = []
    username_profile_list = []
    for users in final_suggestions_list:
        username_profile.append(users.id)

    for user_id in username_profile:
        profile_lists = TheProfile.objects.filter(id_user=user_id)
        username_profile_list.append(profile_lists)

    suggestions_username_profile_list = list(chain(*username_profile_list))

    return render(request, 'following.html', {
        'feed_list': feed_list,
        'user_profile': user_profile,
        'suggestions_username_profile_list': suggestions_username_profile_list
    })


def explore(request):
   user_profile = None
   if request.user.is_authenticated:
       try:
            user_object = User.objects.get(username=request.user.username)
            user_profile = TheProfile.objects.get(user=user_object)
       except TheProfile.DoesNotExist:
            # If the user profile doesn't exist, use the default profile
            user_profile = TheProfile.objects.get(profileimg=True)
   return render(request, 'explore.html', {'user_profile':user_profile})


def discover(request):
   user_profile = None
   if request.user.is_authenticated:
       try:
            user_object = User.objects.get(username=request.user.username)
            user_profile = TheProfile.objects.get(user=user_object)
       except TheProfile.DoesNotExist:
            # If the user profile doesn't exist, use the default profile
            user_profile = TheProfile.objects.get(profileimg=True)
   return render(request, 'discover.html', {'user_profile':user_profile})


@login_required
def delete_post(request, post_id):
    try:
        post_uuid = uuid.UUID(post_id)
    except ValueError:
        messages.error(request, 'Invalid post ID')
        return redirect('profile', pk=request.user.username)
        
    post = get_object_or_404(Image, id=post_uuid)
    if request.method == 'POST':
        if request.user == post.user:
            post.delete()
            messages.success(request, "Post deleted successfully.")
            return redirect(reverse('profile', kwargs={'pk': request.user.username}))
        else:
            messages.error(request, 'You are not allowed to delete this post')
    return render(request, 'profile.html', {'post': post})


def delete_user_images(user):
    images = Image.objects.filter(user=user)
    for image in images:
        if image.file and os.path.isfile(image.file.path):
            os.remove(image.file.path)
    images.delete()


def delete_user_profile_image(user):
    try:
        profile = TheProfile.objects.get(user=user)
        if profile.profileimg and os.path.isfile(profile.profileimg.path):
            os.remove(profile.profileimg.path)
        profile.delete()
    except TheProfile.DoesNotExist:
        pass


@login_required
def delete_account(request):
    user = request.user
    if request.method == 'POST':
        delete_user_images(user)
        delete_user_profile_image(user)

        # Delete the user
        user.delete()

        messages.success(request, "Account deleted successfully.")
        logout(request)
        return redirect('signIn')
    return render(request, 'user_settings.html')


@login_required
def remove_profile_picture(request):
    profile = get_object_or_404(TheProfile, user=request.user)
    if request.method == 'POST':
        if profile.profileimg and os.path.isfile(profile.profileimg.path) and profile.profileimg != 'profile_images/blank_pic.jpg':
            os.remove(profile.profileimg.path)
        profile.profileimg = 'blank_pic.jpg'
        profile.save()
        messages.success(request, "Profile picture removed successfully.")
        return redirect('user_settings', pk=profile.user.id)
    return render(request, 'user_settings.html', {'profile': profile})



#comments view
@login_required
def image_detail(request, file_id):
    file = get_object_or_404(Image, id=file_id)
    user_profile = TheProfile.objects.get(user = request.user)
    comments = Comment.objects.filter(file=file, parent__isnull=True).order_by('-date')
    if request.method == 'POST':
        form = CommentForm(request.POST)
        if form.is_valid():
            parent_id = request.POST.get('parent')
            parent_comment = None
            if parent_id:
                parent_comment = Comment.objects.get(id=parent_id)
            new_comment = form.save(commit=False)
            new_comment.user = request.user
            new_comment.file = file
            new_comment.parent = parent_comment
            new_comment.save()
            # return redirect('image_detail', file_id=file.id)
            return redirect(f'{request.path}#comment-{new_comment.id}')
    else:
        form = CommentForm()

    context = {
        'file': file,
        'comments': comments,
        'form': form,
        'user_profile':user_profile
    }
    return render(request, 'image_detail.html', context)


@login_required
def delete_comment(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id, user=request.user)
    file_id = comment.file.id
    comment.delete()
    messages.success(request, "Comment deleted successfully.")
    return redirect('image_detail', file_id=file_id)

#handle error
def handler404(request, exception):
    return render(request, 'custom-error.html', status=404)


def handler500(request):
    return render(request, 'custom-error.html', status=500)

#user search
def recent_searches(request):
    recent_searches = RecentSearch.objects.filter(user=request.user).values('search_term')[:10]
    return render(request, 'index.html', {'recent_searches': list(recent_searches)})

def user_suggestions(request):
    q = request.GET.get('q', '')
    user_suggestions = User.objects.filter(username__icontains=q).values('username')[:5]
    return render(request, 'index.html', {'user_suggestions': list(user_suggestions)})
  

