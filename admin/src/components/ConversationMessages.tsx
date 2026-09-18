"use client";

import { useState } from "react";

interface Message {
  role: string;
  content: string;
}

/**
 * Islas de cliente para mostrar los últimos mensajes de una conversación.
 * Los mensajes llegan ya renderizados desde el servidor (sin fetch extra).
 */
export function ConversationMessages({ messages }: { messages: Message[] }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="btn btn-ghost"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? "Ocultar mensajes" : `Ver mensajes (${messages.length})`}
      </button>
      {open && (
        <div className="msg-list">
          {messages.map((m, i) => (
            <div
              key={i}
              className={`msg ${m.role === "USER" ? "msg-user" : "msg-assistant"}`}
            >
              <span className="msg-role">
                {m.role === "USER" ? "Cliente" : "Asistente"}
              </span>
              {m.content}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
