"""Quiet methodology links, displayed separately from research controls."""
import streamlit as st


def help_link(label, render, *, key):
    if st.button(label, type='tertiary', key=key):
        @st.dialog(label, width='medium')
        def show():
            render()
        show()
