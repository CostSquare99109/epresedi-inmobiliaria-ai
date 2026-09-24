"use client";

import { Icon } from "./icons";

interface ErrorBannerProps {
  title?: string;
  message: string;
}

export function ErrorBanner({ title = "Error", message }: ErrorBannerProps) {
  return (
    <div className="error-banner">
      <Icon name="alert" size={15} />
      <div>
        <p className="error-banner-title">{title}</p>
        <p className="error-banner-msg">{message}</p>
      </div>
    </div>
  );
}