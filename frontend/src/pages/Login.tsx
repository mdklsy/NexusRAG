import { Button, Card, Form, Input, message } from "antd";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../stores/auth";

export default function Login() {
  const nav = useNavigate();
  const { login } = useAuth();

  const onFinish = async (values: { email: string; password: string }) => {
    try {
      const data = await api.post<{
        token: string;
        user: { email: string; role: string };
      }>("/api/v1/auth/login", values);
      login(data.token, data.user.email, data.user.role);
      nav("/");
    } catch (e: any) {
      message.error(e.message || "登录失败");
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
      }}
    >
      <Card style={{ width: 380 }}>
        <h2 style={{ textAlign: "center", marginBottom: 24 }}>
          Nexus<span style={{ color: "#1677ff" }}>RAG</span> 控制台
        </h2>
        <Form onFinish={onFinish} layout="vertical">
          <Form.Item name="email" label="邮箱" rules={[{ required: true, message: "请输入邮箱" }]}>
            <Input placeholder="admin@nexusrag.local" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: "请输入密码" }]}
          >
            <Input.Password placeholder="••••••" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            登 录
          </Button>
        </Form>
      </Card>
    </div>
  );
}
