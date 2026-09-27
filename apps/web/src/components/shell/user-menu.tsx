"use client";

import { CheckIcon, LogOutIcon, MonitorIcon, MoonIcon, SettingsIcon, SunIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { useTheme, type ThemePreference } from "@/lib/theme";
import {
  Avatar,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-search-growth-os/ui";

const THEME_OPTIONS: { value: ThemePreference; label: string; icon: typeof SunIcon }[] = [
  { value: "system", label: "System theme", icon: MonitorIcon },
  { value: "light", label: "Light", icon: SunIcon },
  { value: "dark", label: "Dark", icon: MoonIcon },
];

export function UserMenu() {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const router = useRouter();
  if (!user) return null;

  const displayName = user.full_name || user.email;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="rounded-full" aria-label="Open user menu">
          <Avatar name={displayName} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="flex flex-col">
          <span className="truncate">{displayName}</span>
          <span className="text-muted-foreground truncate text-xs font-normal">{user.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/app/settings">
            <SettingsIcon />
            Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {THEME_OPTIONS.map((o) => (
          <DropdownMenuItem key={o.value} onSelect={() => setTheme(o.value)} aria-checked={theme === o.value} role="menuitemradio">
            <o.icon />
            {o.label}
            {theme === o.value && <CheckIcon className="ml-auto size-4" aria-hidden="true" />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          variant="destructive"
          onSelect={async () => {
            try {
              await logout();
            } finally {
              // Local auth state is cleared even when the server call fails;
              // the user must always end up on the login page.
              router.replace("/login");
            }
          }}
        >
          <LogOutIcon />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
