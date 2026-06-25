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
    path('guidelines/',               views.guidelines_view,       name='guidelines'),
    path('api/news/',                 views.news_api_view,         name='news_api'),
    path('report/',                   views.report_view,           name='report'),
    path('incidents/',                views.incident_list_view,    name='incidents'),
    path('incidents/<int:pk>/',       views.incident_detail_view,  name='incident_detail'),
    path('incidents/<int:pk>/confirm/',  views.confirm_incident_view,  name='confirm_incident'),
    path('incidents/<int:pk>/dispute/',  views.dispute_incident_view,  name='dispute_incident'),
    path('incidents/<int:pk>/flag/',     views.flag_incident_view,     name='flag_incident'),

    # ---- Moderation queue (staff only) ----
    path('moderation/',                       views.moderation_queue_view,    name='moderation_queue'),
    path('moderation/<int:pk>/hide/',         views.moderation_hide_view,     name='moderation_hide'),
    path('moderation/<int:pk>/unhide/',       views.moderation_unhide_view,   name='moderation_unhide'),
    path('moderation/<int:pk>/dismiss/',      views.moderation_dismiss_view,  name='moderation_dismiss'),
    path('profile/',                  views.profile_view,          name='profile'),

    # ----Edit and Delete ----
    path('incidents/<int:pk>/edit/',   views.edit_incident_view,   name='edit_incident'),
    path('incidents/<int:pk>/delete/', views.delete_incident_view, name='delete_incident'),

    # ---- Feed ----
    path('feed/',                          views.feed_view,           name='feed'),
    path('feed/<int:pk>/save/',            views.save_incident_view,  name='save_incident'),
    path('incidents/<int:pk>/add-photo/',  views.add_photo_view,      name='add_photo'),
    path('incidents/<int:pk>/comment/',   views.feed_comment_view,   name='feed_comment'),

    # ---- Area API (cascading dropdowns + search on report form) ----
    path('api/areas/children/',  views.area_children_view,  name='area_children'),
    path('api/areas/search/',    views.area_search_view,    name='area_search'),
    path('api/areas/resolve/',   views.area_resolve_view,   name='area_resolve'),

    # ---- Area Dashboard ----
    path('areas/',               views.area_search_page_view, name='area_search_page'),
    path('areas/<slug:slug>/',   views.area_detail_view,      name='area_detail'),
]
