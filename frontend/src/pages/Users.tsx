import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  message,
} from "antd";
import { PlusOutlined, UserOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";

interface UserRow {
  id: string;
  email: string;
  name: string;
  role: string;
}

const ROLE_TAG: Record<string, [string, string]> = {
  admin: ["red", "管理员"],
  editor: ["blue", "编辑"],
  viewer: ["default", "只读"],
};

export default function Users() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const { data: users, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<UserRow[]>("/api/v1/users"),
  });

  const create = useMutation({
    mutationFn: (v: any) => api.post("/api/v1/users", v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      setOpen(false);
      form.resetFields();
      message.success("用户已创建");
    },
    onError: (e: any) => message.error(e.message),
  });

  const update = useMutation({
    mutationFn: ({ id, ...rest }: any) => api.put(`/api/v1/users/${id}`, rest),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      message.success("已保存");
    },
    onError: (e: any) => message.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/v1/users/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      message.success("已删除");
    },
    onError: (e: any) => message.error(e.message),
  });

  return (
    <Card
      title="用户管理"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          添加用户
        </Button>
      }
    >
      <Table<UserRow>
        rowKey="id"
        loading={isLoading}
        dataSource={users}
        pagination={false}
        columns={[
          {
            title: "用户",
            render: (_, r) => (
              <Space>
                <UserOutlined />
                <div>
                  <div>{r.email}</div>
                </div>
              </Space>
            ),
          },
          {
            title: "角色",
            dataIndex: "role",
            width: 120,
            render: (v) => {
              const [color, text] = ROLE_TAG[v] || ["default", v];
              return <Tag color={color}>{text}</Tag>;
            },
          },
          {
            title: "操作",
            width: 260,
            render: (_, r) => (
              <Space>
                <Select
                  size="small"
                  defaultValue={r.role}
                  style={{ width: 110 }}
                  disabled={r.id === users?.[0]?.id && false}
                  onChange={(role) => update.mutate({ id: r.id, role })}
                  options={[
                    { value: "admin", label: "管理员" },
                    { value: "editor", label: "编辑" },
                    { value: "viewer", label: "只读" },
                  ]}
                />
                <Button
                  size="small"
                  onClick={() => {
                    Modal.confirm({
                      title: `重置 ${r.email} 的密码`,
                      content: (
                        <Input.Password
                          id="reset-pwd"
                          placeholder="新密码（至少 6 位）"
                          style={{ marginTop: 8 }}
                        />
                      ),
                      onOk: async () => {
                        const el = document.getElementById(
                          "reset-pwd"
                        ) as HTMLInputElement;
                        const pwd = el?.value;
                        if (!pwd || pwd.length < 6) {
                          message.error("密码至少 6 位");
                          return;
                        }
                        update.mutate({ id: r.id, password: pwd });
                      },
                    });
                  }}
                >
                  重置密码
                </Button>
                <Popconfirm title={`删除用户 ${r.email}？`} onConfirm={() => remove.mutate(r.id)}>
                  <Button size="small" danger type="text">
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title="添加用户"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.validateFields().then((v) => create.mutate(v))}
        confirmLoading={create.isPending}
      >
        <Form form={form} layout="vertical" initialValues={{ role: "editor" }}>
          <Form.Item name="email" label="邮箱" rules={[{ required: true, type: "email" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="name" label="姓名">
            <Input />
          </Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 6 }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="role" label="角色">
            <Select
              options={[
                { value: "admin", label: "管理员（含用户管理）" },
                { value: "editor", label: "编辑（应用/知识库读写）" },
                { value: "viewer", label: "只读（浏览 + 对话调试）" },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
