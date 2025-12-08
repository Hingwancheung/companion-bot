#!/bin/bash

echo "🔍 Checking running bot instances..."
echo "-----------------------------------"

# 检查 systemd 状态
systemctl_status=$(sudo systemctl is-active companion-bot)
if [ "$systemctl_status" = "active" ]; then
    echo "✅ systemd bot is running."
else
    echo "⚠️  systemd bot is NOT running."
fi

# 检查 python 实例
python_pids=$(pgrep -f "bot.py")

if [ -n "$python_pids" ]; then
    echo ""
    echo "🧠 Detected Python processes:"
    ps -fp $python_pids
    count=$(echo "$python_pids" | wc -w)
    if [ "$count" -gt 1 ]; then
        echo ""
        read -p "⚠️  Found $count running bot processes. Clean up duplicates? (y/n): " choice
        if [[ "$choice" == [Yy]* ]]; then
            sudo pkill -f "bot.py"
            echo "🧹 Cleaned up all python bot instances."
            echo "🔄 Restarting systemd bot..."
            sudo systemctl restart companion-bot
            echo "✅ Restart complete."
        else
            echo "⚪ No action taken."
        fi
    else
        echo "🟢 Only one bot instance detected — all good."
    fi
else
    echo "💤 No stray python processes found."
fi
