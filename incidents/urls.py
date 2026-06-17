# incidents/urls.py

from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # ---- Public ----
    path('',                          views.landing_view,          name='landing'),
    path('register/',                 views.register_view,         name='register'),
    path('login/',                    views.login_view,            name='login'),
    path('logout/',                   views.logout_view,           name='logout'),

    # ---- Password Reset (Django built-in flow) ----
    path('password-reset/',
         auth_views.PasswordResetView.as_view(
             template_name='registration/password_reset.html'
         ),
         name='password_reset'),
    path('password-reset/done/',
         auth_views.PasswordResetDoneView.as_view(
             template_name='registration/password_reset_done.html'
         ),
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(
             template_name='registration/password_reset_confirm.html'
         ),
         name='password_reset_confirm'),
    path('password-reset-complete/',
         auth_views.PasswordResetCompleteView.as_view(
             template_name='registration/password_reset_complete.html'
         ),
         name='password_reset_complete'),

    # ---- Authenticated App ----
    path('map/',                      views.map_view,              name='map'),
    path('report/',                   views.report_view,           name='report'),
    path('incidents/',                views.incident_list_view,    name='incidents'),
    path('incidents/<int:pk>/',       views.incident_detail_view,  name='incident_detail'),
    path('incidents/<int:pk>/confirm/',  views.confirm_incident_view,  name='confirm_incident'),
    path('incidents/<int:pk>/dispute/',  views.dispute_incident_view,  name='dispute_incident'),
    path('profile/',                  views.profile_view,          name='profile'),

    # ----Edit and Delete ----
    path('incidents/<int:pk>/edit/',   views.edit_incident_view,   name='edit_incident'),
    path('incidents/<int:pk>/delete/', views.delete_incident_view, name='delete_incident'),

    # ---- Feed ----
    path('feed/',                          views.feed_view,           name='feed'),
    path('feed/<int:pk>/save/',            views.save_incident_view,  name='save_incident'),
    path('incidents/<int:pk>/add-photo/',  views.add_photo_view,      name='add_photo'),
    path('incidents/<int:pk>/comment/',   views.feed_comment_view,   name='feed_comment'),
]
