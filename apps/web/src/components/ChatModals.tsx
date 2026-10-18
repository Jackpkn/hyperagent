"use client";

import { useState } from "react";
import { Brain, MessagesSquare, Plus, Trash2, X } from "lucide-react";
import type { ChatSummary } from "@/lib/use-chats";
import { MAX_MEMORIES, MAX_MEMORY_CHARS } from "@/lib/chat-model";

interface ModalFrameProps {
  title: string;
  titleId: string;
  icon: React.ReactNode;
  onClose: () => void;
  actions?: React.ReactNode;
  children: React.ReactNode;
}

function ModalFrame({ title, titleId, icon, onClose, actions, children }: ModalFrameProps) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="modal-card modal-card-wide">
        <div className="modal-head">
          <div className="modal-title-group">
            {icon}
            <h2 id={titleId} className="modal-title">
              {title}
            </h2>
          </div>
          <div className="modal-head-actions">
            {actions}
            <button type="button" className="btn btn-quiet btn-sm" onClick={onClose} aria-label="Close">
              <X size={15} />
            </button>
          </div>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

interface ChatsModalProps {
  chats: ChatSummary[];
  activeId: string | null;
  persistent: boolean;
  onOpen: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

export function ChatsModal({ chats, activeId, persistent, onOpen, onNew, onDelete, onClose }: ChatsModalProps) {
  return (
    <ModalFrame
      title={`Chats (${chats.length})`}
      titleId="chats-modal-title"
      icon={<MessagesSquare size={16} className="modal-icon" aria-hidden="true" />}
      onClose={onClose}
      actions={
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => {
            onNew();
            onClose();
          }}
        >
          <Plus size={13} aria-hidden="true" />
          <span>New chat</span>
        </button>
      }
    >
      <p className="modal-desc">
        {persistent
          ? "Chats, their steps and screenshots are saved in this browser only, so they survive a reload. Nothing is stored on the server."
          : "This browser blocks site storage, so chats last only until you reload the page."}
      </p>
      {chats.length === 0 ? (
        <div className="empty-state" style={{ padding: "28px 12px" }}>
          <MessagesSquare size={22} className="empty-icon" aria-hidden="true" />
          <p className="empty-title">No chats yet</p>
          <p className="empty-sub">Every question you ask starts or continues a chat, and it appears here.</p>
        </div>
      ) : (
        <ul className="history-list">
          {chats.map((chat) => (
            <li key={chat.id} className="history-item" data-active={chat.id === activeId}>
              <div className="history-item-main">
                <div className="history-item-top">
                  <span className="history-date">
                    {new Date(chat.updatedAt).toLocaleString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                  <span className="history-metrics">
                    {chat.turns} {chat.turns === 1 ? "question" : "questions"}
                    {chat.id === activeId ? " · open now" : ""}
                  </span>
                </div>
                <p className="history-goal">{chat.title}</p>
              </div>
              <div className="history-item-actions">
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    onOpen(chat.id);
                    onClose();
                  }}
                >
                  Open
                </button>
                <button
                  type="button"
                  className="btn btn-quiet btn-sm"
                  onClick={() => onDelete(chat.id)}
                  aria-label={`Delete chat: ${chat.title}`}
                  title="Delete this chat and its screenshots"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </ModalFrame>
  );
}

interface MemoryModalProps {
  memories: string[];
  onChange: (next: string[]) => void;
  onClose: () => void;
}

export function MemoryModal({ memories, onChange, onClose }: MemoryModalProps) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const text = draft.trim().slice(0, MAX_MEMORY_CHARS);
    if (!text || memories.some((m) => m.toLowerCase() === text.toLowerCase())) return;
    onChange([...memories, text].slice(-MAX_MEMORIES));
    setDraft("");
  };

  return (
    <ModalFrame
      title={`Memory (${memories.length})`}
      titleId="memory-modal-title"
      icon={<Brain size={16} className="modal-icon" aria-hidden="true" />}
      onClose={onClose}
      actions={
        memories.length > 0 ? (
          <button type="button" className="btn btn-quiet btn-sm" onClick={() => onChange([])}>
            <Trash2 size={13} aria-hidden="true" />
            <span>Forget all</span>
          </button>
        ) : null
      }
    >
      <p className="modal-desc">
        The agent applies these in every chat. It only saves things you said yourself, never text from
        web pages. Edit or delete anything here.
      </p>
      {memories.length === 0 ? (
        <p className="memory-empty">Nothing remembered yet. Tell the agent a lasting preference, such as &ldquo;show prices in INR&rdquo;, or add one below.</p>
      ) : (
        <ul className="memory-list">
          {memories.map((memory, index) => (
            <li key={`${index}-${memory}`} className="memory-item">
              <input
                className="input"
                aria-label={`Memory ${index + 1}`}
                defaultValue={memory}
                maxLength={MAX_MEMORY_CHARS}
                onBlur={(event) => {
                  const text = event.target.value.trim();
                  if (text === memory) return;
                  onChange(text ? memories.map((m, i) => (i === index ? text : m)) : memories.filter((_, i) => i !== index));
                }}
              />
              <button
                type="button"
                className="btn btn-quiet btn-sm"
                onClick={() => onChange(memories.filter((_, i) => i !== index))}
                aria-label={`Forget: ${memory}`}
              >
                <Trash2 size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="memory-add"
        onSubmit={(event) => {
          event.preventDefault();
          add();
        }}
      >
        <input
          className="input"
          placeholder="Add something to remember…"
          aria-label="New memory"
          value={draft}
          maxLength={MAX_MEMORY_CHARS}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" className="btn btn-sm" disabled={!draft.trim() || memories.length >= MAX_MEMORIES}>
          <Plus size={13} aria-hidden="true" />
          <span>Add</span>
        </button>
      </form>
    </ModalFrame>
  );
}
