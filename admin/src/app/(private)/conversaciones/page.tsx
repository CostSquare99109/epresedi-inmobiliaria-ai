import type { Metadata } from "next";
import { backend, type ConversationDTO } from "@/lib/backend";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { RefreshButton } from "@/components/RefreshButton";
import { ConversationMessages } from "@/components/ConversationMessages";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Conversaciones" };

export default async function Conversaciones() {
  let convs: ConversationDTO[] = [];
  let error = "";
  try {
    const body = await backend<{ conversations: ConversationDTO[] }>("/conversations");
    convs = body.conversations;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <>
      <PageHeader
        title="Conversaciones"
        description="Resumen y últimos mensajes intercambiados entre los clientes y el asistente."
        actions={<RefreshButton />}
      />

      {error && <ErrorBanner message={error} />}

      {!error &&
        (convs.length === 0 ? (
          <div className="card">
            <EmptyState
              icon="chat"
              title="Sin conversaciones"
              description="Cuando los usuarios interactúen con el asistente por Telegram, cada conversación aparecerá aquí con su resumen."
            />
          </div>
        ) : (
          <div className="conv-grid">
            {convs.map((c) => (
              <section
                className="card"
                key={c.id}
                aria-label={`Conversación con usuario ${c.user_id}`}
              >
                <div className="card-head">
                  <div>
                    <h2 className="card-title">Usuario #{c.user_id}</h2>
                    <p className="card-sub">
                      {c.recent.length} mensaje{c.recent.length === 1 ? "" : "s"} recientes
                    </p>
                  </div>
                </div>
                <div className="card-body">
                  {c.summary && <p className="card-intro">{c.summary}</p>}
                  <ConversationMessages messages={c.recent} />
                </div>
              </section>
            ))}
          </div>
        ))}
    </>
  );
}
