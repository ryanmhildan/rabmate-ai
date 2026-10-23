"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Field, FormError, Input } from "@/components/ui/Field";
import { api, errorMessage } from "@/lib/api";
import { ME_QUERY_KEY, safeNextPath } from "@/lib/auth";
import type { Me } from "@/lib/types";

const schema = z.object({
  email: z.string().trim().min(1, "Email wajib diisi.").email("Format email tidak valid."),
  password: z.string().min(1, "Kata sandi wajib diisi.").max(128),
});

type Values = z.infer<typeof schema>;

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { email: "", password: "" } });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const me = await api.post<Me>("/auth/login", values);
      queryClient.setQueryData(ME_QUERY_KEY, me);
      router.replace(safeNextPath(params.get("next")));
    } catch (error) {
      setFormError(errorMessage(error));
    }
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <FormError message={formError} />
      <Field label="Email" error={errors.email?.message} required>
        {(a11y) => (
          <Input type="email" autoComplete="username" autoFocus {...a11y} {...register("email")} />
        )}
      </Field>
      <Field label="Kata sandi" error={errors.password?.message} required>
        {(a11y) => (
          <Input type="password" autoComplete="current-password" {...a11y} {...register("password")} />
        )}
      </Field>
      <Button type="submit" className="w-full" loading={isSubmitting}>
        Masuk
      </Button>
    </form>
  );
}
