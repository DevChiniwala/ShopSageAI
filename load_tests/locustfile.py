from locust import HttpUser, task, between

class ShopSageUser(HttpUser):
    # Wait between 1 to 3 seconds between tasks to simulate real human behavior
    wait_time = between(1, 3)

    def on_start(self):
        """Called when a user starts. We can set up auth headers or session IDs here."""
        self.client.headers.update({"Content-Type": "application/json"})
        self.session_id = "locust_load_test_" + str(self.environment.runner.user_count)

    @task(3)
    def view_homepage(self):
        """Simulate user loading the main chat interface."""
        self.client.get("/")

    @task(5)
    def send_chat_message(self):
        """Simulate a user chatting with the AI bot."""
        payload = {
            "message": "I'm looking for a new high-refresh rate gaming monitor under $500.",
            "session_id": self.session_id
        }
        with self.client.post("/chat", json=payload, catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Chat failed with status {response.status_code}")

    @task(1)
    def check_health(self):
        """Simulate LB/Kubernetes health checks hitting the server."""
        self.client.get("/health/liveness")
