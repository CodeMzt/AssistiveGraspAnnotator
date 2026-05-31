import "react";

declare module "react" {
  interface InputHTMLAttributes<T> {
    directory?: string;
    webkitdirectory?: string;
  }
}
