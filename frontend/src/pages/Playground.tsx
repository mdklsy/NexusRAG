import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { SendOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { api, chatStream } from "../api/client";
import { useRef, useState } from "react";

interface Citation {
  index: number;
  document_name: string;
  heading: string;
  snippet: string;
  score: number;
}

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  meta?: string;
  tools?: { name: string; ok: boolean }[];
}

export default function Playground() {
  const [appId, setAppId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const conversationRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const { data: apps } = useQuery({
    queryKey: ["apps"],
    queryFn: () => api.get<any[]>("/api/v1/apps"),
  });

  const send = async () => {
    if (!input.trim() || !appId || busy) return;
    const question = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", content: question }, { role: "assistant", content: "" }]);
    setBusy(true);
    let metaInfo = "";
    let toolCalls: { name: string; ok: boolean }[] = [];
    try {
      await chatStream(
        {
          app_id: appId,
          conversation_id: conversationRef.current,
          query: question,
        },
        (ev) => {
          if (ev.type === "conversation") {
            conversationRef.current = ev.conversation_id;
          } else if (ev.type === "delta") {
            setMessages((m) => {
              const copy = [...m];
              copy[copy.length - 1] = {
                ...copy[copy.length - 1],
                content: copy[copy.length - 1].content + ev.content,
              };
              return copy;
            });
          } else if (ev.type === "citations") {
            setMessages((m) => {
              const copy = [...m];
              copy[copy.length - 1] = { ...copy[copy.length - 1], citations: ev.citations };
              return copy;
            });
          } else if (ev.type === "retrieval") {
            metaInfo = `命中 ${ev.chunks} 块 · 图谱事实 ${ev.graph_facts} 条`;
          } else if (ev.type === "tool_call") {
            toolCalls.push({ name: ev.name, ok: true });
            setMessages((m) => {
              const copy = [...m];
              copy[copy.length - 1] = { ...copy[copy.length - 1], tools: [...toolCalls] };
              return copy;
            });
          } else if (ev.type === "tool_result") {
            if (toolCalls.length) toolCalls[toolCalls.length - 1].ok = ev.ok;
            setMessages((m) => {
              const copy = [...m];
              copy[copy.length - 1] = { ...copy[copy.length - 1], tools: [...toolCalls] };
              return copy;
            });
          } else if (ev.type === "done") {
            metaInfo += ` · ${ev.latency_ms}ms`;
            setMessages((m) => {
              const copy = [...m];
              copy[copy.length - 1] = { ...copy[copy.length - 1], meta: metaInfo };
              return copy;
            });
          } else if (ev.type === "error") {
            setMessages((m) => {
              const copy = [...m];
              copy[copy.length - 1] = {
                ...copy[copy.length - 1],
                content: `⚠️ ${ev.message}`,
              };
              return copy;
            });
          }
          bottomRef.current?.scrollIntoView({ behavior: "smooth" });
        }
      );
    } catch (e: any) {
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { ...copy[copy.length - 1], content: `⚠️ ${e.message}` };
        return copy;
      });
    }
    setBusy(false);
  };

  return (
    <Card
      title="Playground 对话调试"
      extra={
        <Space>
          <Select
            style={{ width: 220 }}
            placeholder="选择应用"
            value={appId}
            onChange={() => {
              setMessages([]);
              conversationRef.current = null;
            }}
            options={(apps || []).map((a) => ({ value: a.id, label: `${a.icon} ${a.name}` }))}
          />
          <Button
            onClick={() => {
              setMessages([]);
              conversationRef.current = null;
            }}
          >
            新对话
          </Button>
        </Space>
      }
    >
      {!appId && <Empty description="先选择一个应用" style={{ padding: 60 }} />}
      {appId && (
        <div style={{ height: "calc(100vh - 280px)", overflow: "auto", padding: "0 4px" }}>
          {messages.length === 0 && (
            <Empty description="提问试试，例如：我们的退款政策是什么？" style={{ paddingTop: 80 }} />
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                justifyContent: m.role === "user" ? "flex-end" : "flex-start",
                marginBottom: 14,
              }}
            >
              <div
                style={{
                  maxWidth: "78%",
                  padding: "10px 14px",
                  borderRadius: 10,
                  background: m.role === "user" ? "#1677ff" : "#fff",
                  color: m.role === "user" ? "#fff" : "#333",
                  border: m.role === "user" ? "none" : "1px solid #eee",
                  whiteSpace: "pre-wrap",
                }}
              >
                {m.content || (busy && i === messages.length - 1 ? <Spin size="small" /> : "")}
                {m.tools && m.tools.length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    {m.tools.map((t, ti) => (
                      <Tag key={ti} color={t.ok === false ? "red" : "geekblue"} style={{ fontSize: 11 }}>
                        ⚙ {t.name}
                      </Tag>
                    ))}
                  </div>
                )}
                {m.citations && m.citations.length > 0 && (
                  <div style={{ marginTop: 8, borderTop: "1px dashed #ddd", paddingTop: 8 }}>
                    <Typography.Text strong style={{ fontSize: 12 }}>
                      引用来源
                    </Typography.Text>
                    {m.citations.map((c) => (
                      <Tag key={c.index} style={{ marginTop: 4 }}>
                        [{c.index}] {c.document_name}
                        {c.heading ? ` · ${c.heading}` : ""}（{c.score.toFixed(2)}）
                      </Tag>
                    ))}
                  </div>
                )}
                {m.meta && (
                  <Typography.Text
                    type="secondary"
                    style={{ fontSize: 11, display: "block", marginTop: 6 }}
                  >
                    {m.meta}
                  </Typography.Text>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}
      <div style={{ display: "flex", gap: 12, marginTop: 12 }}>
        <Input
          size="large"
          placeholder={appId ? "输入问题，Enter 发送" : "请先选择应用"}
          disabled={!appId || busy}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={send}
        />
        <Button type="primary" size="large" icon={<SendOutlined />} onClick={send} loading={busy} disabled={!appId}>
          发送
        </Button>
      </div>
      {!apps?.length && (
        <Alert
          style={{ marginTop: 12 }}
          type="info"
          message="还没有应用：先到「知识库」上传文档，再到「应用」创建并绑定。"
        />
      )}
    </Card>
  );
}
