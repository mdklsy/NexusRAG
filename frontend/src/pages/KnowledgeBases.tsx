import { Button, Card, Empty, Form, Input, Modal, Popconfirm, Space, Table, message } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useState } from "react";

interface KB {
  id: string;
  name: string;
  description: string;
  embedding_model: string;
  doc_count: number;
  chunk_count: number;
  created_at: string;
}

export default function KnowledgeBases() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const { data: kbs, isLoading } = useQuery({
    queryKey: ["kbs"],
    queryFn: () => api.get<KB[]>("/api/v1/kbs"),
  });

  const create = useMutation({
    mutationFn: (values: { name: string; description: string }) =>
      api.post("/api/v1/kbs", values),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kbs"] });
      setOpen(false);
      form.resetFields();
      message.success("知识库已创建");
    },
    onError: (e: any) => message.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/v1/kbs/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kbs"] });
      message.success("已删除");
    },
    onError: (e: any) => message.error(e.message),
  });

  return (
    <Card
      title="知识库"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          新建知识库
        </Button>
      }
    >
      <Table<KB>
        rowKey="id"
        loading={isLoading}
        dataSource={kbs}
        locale={{ emptyText: <Empty description="还没有知识库，先创建一个" /> }}
        onRow={(r) => ({ onClick: () => nav(`/kbs/${r.id}`), style: { cursor: "pointer" } })}
        columns={[
          { title: "名称", dataIndex: "name" },
          { title: "描述", dataIndex: "description", ellipsis: true },
          { title: "文档数", dataIndex: "doc_count", width: 90 },
          { title: "分块数", dataIndex: "chunk_count", width: 90 },
          { title: "向量模型", dataIndex: "embedding_model", width: 180 },
          {
            title: "操作",
            width: 90,
            render: (_, r) => (
              <Space onClick={(e) => e.stopPropagation()}>
                <Popconfirm
                  title="删除知识库及其全部数据？"
                  onConfirm={() => remove.mutate(r.id)}
                >
                  <Button danger size="small" type="text">
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title="新建知识库"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.validateFields().then((v) => create.mutate(v))}
        confirmLoading={create.isPending}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="如：产品帮助中心" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
