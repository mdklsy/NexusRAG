// 全局服务设置：对话模型 / 向量模型 / 重排服务（仅 admin）。
// 配置存 DB 并立即生效（约 30 秒内刷新到全部服务），无需重启容器；
// 未设置的项回退部署 .env。

import { useEffect } from "react";
import { Alert, Button, Card, Form, Input, message, Typography } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../stores/auth";

type CatStatus = {
  api_base: string;
  model: string;
  api_key_set: boolean;
  api_key_masked: string;
  from_db: boolean;
};

const CATS: { key: string; title: string; desc: string; modelPlaceholder: string }[] = [
  {
    key: "llm",
    title: "对话模型",
    desc: "回答生成、意图路由、图谱抽取、评测裁判都走这里",
    modelPlaceholder: "deepseek-chat / glm-4-flash / qwen-plus …",
  },
  {
    key: "embedding",
    title: "向量模型",
    desc: "文档摄取与检索的语义向量。更换模型后需重建知识库（旧向量不兼容）",
    modelPlaceholder: "BAAI/bge-m3 / embedding-3 …",
  },
  {
    key: "rerank",
    title: "重排服务",
    desc: "检索候选二次精排（应用检索策略选「托管 API 重排」时使用）",
    modelPlaceholder: "BAAI/bge-reranker-v2-m3 …",
  },
];

function CatForm({ cat, status }: { cat: string; status?: CatStatus }) {
  const [form] = Form.useForm();
  const qc = useQueryClient();

  useEffect(() => {
    form.setFieldsValue({
      api_base: status?.api_base || "",
      model: status?.model || "",
    });
  }, [status?.api_base, status?.model]);

  const save = useMutation({
    mutationFn: (values: any) => api.put(`/api/v1/settings/${cat}`, values),
    onSuccess: () => {
      message.success("已保存，约 30 秒内全服务生效");
      form.setFieldValue("api_key", "");
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (e: any) => message.error(e.message),
  });

  return (
    <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
      <Form.Item
        name="api_base"
        label="API Base"
        tooltip="OpenAI 兼容协议的服务地址，留空 = 用部署 .env 的值"
        extra={<span style={{ fontSize: 12 }}>如 https://api.deepseek.com/v1、https://api.siliconflow.cn/v1</span>}
      >
        <Input placeholder="留空 = 沿用 .env" />
      </Form.Item>
      <Form.Item name="model" label="模型名" extra={<span style={{ fontSize: 12 }}>留空 = 沿用 .env</span>}>
        <Input placeholder={CATS.find((c) => c.key === cat)?.modelPlaceholder} />
      </Form.Item>
      <Form.Item
        name="api_key"
        label="API Key"
        tooltip="保存后 AES 加密入库，页面只显示掩码；留空 = 保持不变"
        extra={
          <span style={{ fontSize: 12 }}>
            {status?.api_key_set
              ? `已设置 ${status.api_key_masked || "(掩码隐藏)"}${status.from_db ? "（来自页面配置）" : "（来自 .env）"}，留空即保持`
              : "未设置，留空 = 沿用 .env"}
          </span>
        }
      >
        <Input.Password placeholder={status?.api_key_set ? "留空 = 保持不变" : "粘贴密钥"} />
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={save.isPending}>
        保存
      </Button>
    </Form>
  );
}

export default function Settings() {
  const { role } = useAuth();
  const { data, isLoading, error } = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<Record<string, CatStatus>>("/api/v1/settings"),
  });

  if (role !== "admin") {
    return <Alert type="warning" showIcon message="仅管理员可访问全局服务设置" />;
  }

  return (
    <Card title="全局服务设置">
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="配置保存后立即生效（约 30 秒内同步到 API / Worker），无需重启容器；未填写的项回退部署 .env"
      />
      {isLoading && <Typography.Text type="secondary">加载中…</Typography.Text>}
      {error && <Alert type="error" showIcon message="加载失败" description={String((error as any)?.message || error)} />}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: 16 }}>
        {CATS.map((c) => (
          <Card
            key={c.key}
            type="inner"
            title={c.title}
            style={{ marginBottom: 16 }}
            extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>{c.desc}</Typography.Text>}
          >
            <CatForm cat={c.key} status={data?.[c.key]} />
          </Card>
        ))}
      </div>
    </Card>
  );
}
