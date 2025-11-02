import os
import streamlit as st
import streamlit.components.v1 as components

_build_dir = os.path.dirname(__file__)
video_hotkeys = components.declare_component(
    "video_hotkeys",
    path=_build_dir
)

def streamlit_video_component(video_url, start_time=0):
    return video_hotkeys(
        video_url=video_url,
        start_time=start_time,
        default={}
    )
