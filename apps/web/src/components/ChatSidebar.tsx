"use client";

// Chats use native history in the static app shell, with full navigation for modified clicks.
/* eslint-disable @next/next/no-html-link-for-pages */

import { Brain, Menu, MessagesSquare, PanelLeftClose, Plus, Trash2, UserCheck } from "lucide-react";
import { chatPath } from "@/lib/chat-path";
import type { ChatSummary } from "@/lib/use-chats";

interface ChatSidebarProps {
  open: boolean;
  chats: ChatSummary[];
  activeId: string | null;
  busy: boolean;
  persistent: boolean;
  ready: boolean;
  hasProfileData: boolean;
  memoryCount: number;
  onToggle: () => void;
  onNew: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onOpenProfile: () => void;
  onOpenMemory: () => void;
}

export function ChatSidebar(props: ChatSidebarProps) {
  const { open, chats, activeId, busy, ready } = props;
  return (
    <aside className={`chat-sidebar${open ? " is-open" : ""}`} aria-label="Workspace">
      <button type="button" className="btn btn-quiet chat-sidebar-toggle" onClick={props.onToggle}
        aria-label={open ? "Collapse chat sidebar" : "Expand chat sidebar"}
        aria-expanded={open} aria-controls="chat-navigation">
        {open ? <PanelLeftClose size={17} /> : <Menu size={17} />}
        <span>Workspace</span>
      </button>
      <div className="chat-navigation" id="chat-navigation">
        <a href="/" className={`launch-nav-item${activeId ? "" : " is-current"}`}
          onClick={(event) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            props.onNew();
          }}>
          <Plus size={16} aria-hidden="true" /> New task
        </a>
        <nav className="chat-list" aria-label="Chats">
          <div className="chat-list-heading"><MessagesSquare size={14} aria-hidden="true" /> Chats</div>
          {!ready ? <p className="hint">Loading chats…</p> : chats.length === 0 ? <p className="hint">No chats yet</p> : null}
          {chats.map((chat) => (
            <div className={`chat-list-item${activeId === chat.id ? " is-current" : ""}`} key={chat.id}>
              <a href={chatPath(chat.id)} aria-current={activeId === chat.id ? "page" : undefined}
                title={chat.title} onClick={(event) => {
                  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                  event.preventDefault();
                  props.onOpen(chat.id);
                }}>{chat.title}</a>
              <button type="button" className="btn btn-quiet chat-delete" aria-label={`Delete chat: ${chat.title}`}
                disabled={busy && activeId === chat.id} onClick={() => props.onDelete(chat.id)}>
                <Trash2 size={13} aria-hidden="true" />
              </button>
            </div>
          ))}
        </nav>
        <div className="chat-sidebar-resources">
          {!props.persistent ? <p className="hint" role="status">Chat storage is unavailable. Changes may be lost on reload.</p> : null}
          <button type="button" className="launch-nav-item" onClick={props.onOpenProfile}>
            <UserCheck size={16} aria-hidden="true" /> Autofill profile
            {props.hasProfileData ? <span className="dot dot-open" role="img" aria-label="Profile active" /> : null}
          </button>
          <button type="button" className="launch-nav-item" onClick={props.onOpenMemory}>
            <Brain size={16} aria-hidden="true" /> Memory
            {props.memoryCount > 0 ? <span className="launch-nav-count">{props.memoryCount}</span> : null}
          </button>
        </div>
      </div>
    </aside>
  );
}
