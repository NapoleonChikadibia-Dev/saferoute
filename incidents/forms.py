# incidents/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Incident, Comment, UserProfile


# ---------------------------------------------------------------------------
# REGISTER
# ---------------------------------------------------------------------------

class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True, help_text='Required.')

    class Meta:
        model  = User
        fields = ['username', 'email', 'password1', 'password2']

    def clean_email(self):
        email = self.cleaned_data.get('email', '').lower()
        # Must start with a letter
        if email and not email[0].isalpha():
            raise forms.ValidationError('Email address must start with a letter.')
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email


# ---------------------------------------------------------------------------
# INCIDENT
# ---------------------------------------------------------------------------

class IncidentForm(forms.ModelForm):
    class Meta:
        model  = Incident
        fields = [
            'title',
            'type',
            'description',
            'location',
            'latitude',
            'longitude',
            'danger_level',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'latitude':    forms.HiddenInput(),
            'longitude':   forms.HiddenInput(),
        }

    def clean_type(self):
        """Allow both predefined choices and custom types."""
        value = self.cleaned_data.get('type', '').strip()
        if not value:
            raise forms.ValidationError('Please select or enter an incident type.')
        # Slugify custom types — lowercase, underscores
        import re
        value = re.sub(r'[^a-z0-9_]', '_', value.lower())[:50]
        return value

    def clean(self):
        cleaned = super().clean()
        lat = cleaned.get('latitude')
        lng = cleaned.get('longitude')
        if lat is None or lng is None:
            raise forms.ValidationError('Please click on the map to select a location.')
        if not (-90 <= lat <= 90):
            raise forms.ValidationError('Invalid latitude value.')
        if not (-180 <= lng <= 180):
            raise forms.ValidationError('Invalid longitude value.')
        return cleaned



# ---------------------------------------------------------------------------
# COMMENT
# ---------------------------------------------------------------------------

class CommentForm(forms.ModelForm):
    class Meta:
        model   = Comment
        fields  = ['body']
        widgets = {
            'body': forms.Textarea(attrs={
                'rows':        3,
                'placeholder': 'Share your experience or thoughts about this incident...',
            })
        }
        labels = {'body': ''}

    def clean_body(self):
        body = self.cleaned_data.get('body', '').strip()
        if len(body) < 5:
            raise forms.ValidationError('Comment must be at least 5 characters.')
        if len(body) > 2000:
            raise forms.ValidationError('Comment cannot exceed 2000 characters.')
        return body


# ---------------------------------------------------------------------------
# USER PROFILE
# ---------------------------------------------------------------------------

class UserProfileForm(forms.ModelForm):
    class Meta:
        model   = UserProfile
        fields  = ['bio', 'avatar', 'sos_phone', 'location']
        widgets = {
            'bio': forms.Textarea(attrs={
                'rows':        3,
                'placeholder': 'Tell the community a bit about yourself...',
            }),
            'sos_phone': forms.TextInput(attrs={
                'placeholder': '+234 800 000 0000',
            }),
            'location': forms.TextInput(attrs={
                'placeholder': 'e.g. Ikeja, Lagos',
            }),
            'avatar': forms.HiddenInput()
        }

    def clean_sos_phone(self):
        phone = self.cleaned_data.get('sos_phone', '').strip()
        # Allow empty — optional field
        if phone and len(phone) < 7:
            raise forms.ValidationError('Enter a valid phone number.')
        return phone
    
from django.contrib.auth.models import User

class UserUpdateForm(forms.ModelForm):
    class Meta:
        model  = User
        fields = ['username', 'email', 'first_name', 'last_name']

    def clean_email(self):
        email = self.cleaned_data.get('email', '').lower()
        # Exclude current user from duplicate check
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('This email is already taken.')
        return email

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if User.objects.filter(username=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('This username is already taken.')
        return username
